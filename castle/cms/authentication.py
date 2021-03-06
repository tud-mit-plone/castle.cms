from Acquisition import aq_parent
from castle.cms import cache
from castle.cms.interfaces import IAuthenticator
from castle.cms.interfaces import ICastleApplication
from castle.cms.lockout import LockoutManager
from castle.cms.utils import get_ip
from castle.cms.utils import get_random_string
from castle.cms.utils import strings_differ
from OFS.interfaces import IItem
from plone import api
from plone.keyring.interfaces import IKeyManager
from plone.keyring.keymanager import KeyManager
from plone.registry.interfaces import IRegistry
from plone.session.plugins.session import manage_addSessionPlugin
from Products.PlonePAS.events import UserLoggedInEvent
from Products.PlonePAS.setuphandlers import activatePluginInterfaces
from Products.PlonePAS.setuphandlers import migrate_root_uf
from Products.PluggableAuthService.interfaces.plugins import IChallengePlugin
from zope.component import adapter
from zope.component import getGlobalSiteManager
from zope.component import getUtility
from zope.component.interfaces import ComponentLookupError
from zope.event import notify
from zope.interface import implementer
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

import time


class AuthenticationException(Exception):
    pass


class AuthenticationCountryBlocked(AuthenticationException):
    pass


class AuthenticationMaxedLoginAttempts(AuthenticationException):
    pass


class AuthenticationUserDisabled(AuthenticationException):
    pass


class AuthenticationPasswordResetWindowExpired(AuthenticationException):
    pass


@implementer(IAuthenticator)
@adapter(IItem, IDefaultBrowserLayer)
class Authenticator(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        try:
            self.registry = getUtility(IRegistry)
            self.two_factor_enabled = self.registry.get(
                'plone.two_factor_enabled', False)
        except ComponentLookupError:
            self.registry = None
            self.two_factor_enabled = False

    @property
    def is_zope_root(self):
        return ICastleApplication.providedBy(self.context)

    def get_tool(self, name):
        if self.is_zope_root:
            return getattr(self.context, name, None)
        else:
            return api.portal.get_tool(name)

    def get_supported_auth_schemes(self):
        auth_schemes = [{
            'id': 'email',
            'label': 'Email'
        }]
        if self.registry:
            if self.registry.get('castle.plivo_auth_id'):
                auth_schemes.append({
                    'id': 'sms',
                    'label': 'SMS'
                })
        return auth_schemes

    def authorize_2factor(self, username, code, offset=0):
        try:
            value = cache.get(self.get_2factor_code_key(username))
        except:
            return False

        # check actual code
        if strings_differ(value['code'].lower(), code.lower()):
            return False

        # then check timing
        timestamp = value.get('timestamp')
        if not timestamp or (time.time() > (timestamp + 5 * 60 + offset)):
            return False
        return True

    def get_2factor_code_key(self, username):
        return '{}-{}-auth-code-attempt'.format(
            '-'.join(self.context.getPhysicalPath()[1:]),
            username
        )

    def issue_2factor_code(self, username):
        cache_key = self.get_2factor_code_key(username)
        code = get_random_string(8).upper()
        # store code to check again later
        cache.set(cache_key, {
            'code': code,
            'timestamp': time.time()
        })
        return code

    def authenticate(self, username=None, password=None, country=None):
        """
        return true if successfull
        """
        if not self.is_zope_root:
            manager = LockoutManager(self.context, username)

            if manager.maxed_number_of_attempts():
                raise AuthenticationMaxedLoginAttempts()

            manager.add_attempt()

        for acl_users in self.get_acl_users():
            # if not root, could be more than one to check against
            user = acl_users.authenticate(username, password, self.request)
            if user:
                break

        if user is None:
            return False, user

        if not self.is_zope_root:
            manager.clear()

        if user.getRoles() == ['Authenticated']:
            raise AuthenticationUserDisabled()

        if self.registry:
            allowed_countries = self.registry.get(
                'plone.restrict_logins_to_countries')
            if allowed_countries and country:
                if country not in allowed_countries:
                    if not self.country_exception_granted(user.getId()):
                        raise AuthenticationCountryBlocked()

        if not self.is_zope_root:
            member = api.user.get(user.getId())
            reset_password = member.getProperty(
                'reset_password_required', False)
            reset_time = member.getProperty('reset_password_time', None)

            if reset_password and reset_time:
                if reset_time + (24 * 60 * 60) < time.time():
                    raise AuthenticationPasswordResetWindowExpired()

        acl_users.session._setupSession(user.getId(), self.request.response)
        notify(UserLoggedInEvent(user))

        return True, user

    def country_exception_granted(self, userid):
        cache_key = self.get_country_exception_cache_key(userid)
        try:
            data = cache.get(cache_key)
        except:
            return False
        timestamp = data.get('timestamp')
        if (data.get('granted') and timestamp and
                (time.time() < (timestamp + (12 * 60 * 60)))):
            return True
        return True

    def get_acl_users(self):
        """
        get list of acl_user objects,
        first, site, then root
        """
        objects = [self.get_tool('acl_users')]
        if not self.is_zope_root:
            context = aq_parent(self.context)
            while context and not ICastleApplication.providedBy(context):
                context = aq_parent(context)
            acl = getattr(context, 'acl_users', None)
            if acl:
                objects.append(acl)
        return objects

    def get_country_exception_cache_key(self, userid):
        return '{}-{}-country-exception'.format(
            '-'.join(self.context.getPhysicalPath()[1:]),
            userid
        )

    def issue_country_exception(self, user, country):
        # capture information about the request
        data = {
            'referrer': self.request.get_header('REFERER'),
            'user_agent': self.request.get_header('USER_AGENT'),
            'ip': get_ip(self.request),
            'username': user.getUserName(),
            'userid': user.getId(),
            'country': country,
            'timestamp': time.time(),
            'code': get_random_string(50),
            'granted': False
        }

        cache_key = self.get_country_exception_cache_key(user.getId())
        cache.set(cache_key, data, 12 * 60 * 60)  # valid for 12 hours

        return data

    def change_password(self, member, new_password):
        user = api.user.get(member.getId())
        user.setMemberProperties(mapping={
            'reset_password_required': False,
            'reset_password_time': time.time()
        })
        member.setSecurityProfile(password=new_password)


def install_acl_users(app, logger=None):
    uf = app.acl_users
    found = uf.objectIds(['Plone Session Plugin'])
    if not found:
        # new root acl user implementation not installed yet
        migrate_root_uf(app)
        uf = app.acl_users  # need to get new acl_users

        plone_pas = uf.manage_addProduct['PlonePAS']
        manage_addSessionPlugin(plone_pas, 'session')
        activatePluginInterfaces(app, "session")

        cookie_auth = uf.credentials_cookie_auth
        cookie_auth.login_path = u'/@@secure-login'

        uf.plugins.activatePlugin(
            IChallengePlugin,
            'credentials_cookie_auth'
        )

        # also delete basic auth
        uf.manage_delObjects(['credentials_basic_auth'])

        # for some reason, we need to install the initial user...
        if not api.env.test_mode():
            try:
                uf.users.manage_addUser('admin', 'admin', 'admin', 'admin')
                uf.roles.assignRoleToPrincipal('Manager', 'admin')
            except KeyError:
                pass  # already a user

        if logger is not None:
            logger('Updated acl users')

    km = getattr(app, 'key_manager', None)
    if km is None:
        km = KeyManager()
        app.key_manager = km
        app._p_changed = 1
        if logger is not None:
            logger('adding key manager')

    sm = getGlobalSiteManager()
    sm.registerUtility(km, IKeyManager)

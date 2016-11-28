# login/lockout and shield integration
from castle.cms import shield
from castle.cms.interfaces import ICastleLayer
from castle.cms.lockout import LOGGED_IN_MARKER_KEY
from castle.cms.lockout import SessionManager
from castle.cms.utils import get_context_from_request
from plone import api
from plone.uuid.interfaces import IUUID
from Products.PluggableAuthService.interfaces.events import IUserLoggedInEvent
from Products.PluggableAuthService.interfaces.events import IUserLoggedOutEvent
from urlparse import urlparse
from zExceptions import Redirect
from zope.component import adapter
from zope.component.hooks import getSite
from zope.globalrequest import getRequest
from ZPublisher.interfaces import IPubAfterTraversal
from ZPublisher.interfaces import IPubBeforeCommit

import logging


log = logging.getLogger(__name__)


@adapter(IUserLoggedOutEvent)
def onUserLogsOut(event):
    request = getRequest()
    if request is None:
        return
    site = api.portal.get()
    user = api.user.get_current()
    try:
        session_manager = SessionManager(site, request, user)
        resp = request.response
        resp.expireCookie(session_manager.cookie_name)
        session_manager.delete()
    except:
        pass


@adapter(IUserLoggedInEvent)
def onUserLogsIn(event):
    """
    let us know that the user was logged in here successfully
    """
    request = getRequest()
    if request is None:
        return
    if not ICastleLayer.providedBy(request):
        return
    request.environ[LOGGED_IN_MARKER_KEY] = 'yes'

    # do not even allow user to login if the account has been
    # disabled
    if api.user.get_roles(user=event.object) == ['Authenticated']:
        site = getSite()
        raise Redirect('%s/@@disabled-user' % site.absolute_url())


@adapter(IPubAfterTraversal)
def afterTraversal(event):
    """
    check it should be blocked by lockout
    """
    request = event.request
    if not ICastleLayer.providedBy(request):
        return

    shield.protect(request)

    resp = request.response

    context = get_context_from_request(request)
    cache_tags = set([
        getattr(context, 'portal_type', '').lower().replace(' ', '-'),
        getattr(context, 'meta_type', '').lower().replace(' ', '-'),
        IUUID(context, ''),
        urlparse(request.URL).netloc.lower().replace('.', '').replace(':', '')
    ])

    resp.setHeader('Cache-Tag', ','.join(t for t in cache_tags if t))

    # Prevent IE and Chrome from incorrectly detecting non-scripts as scripts
    resp.setHeader('X-Content-Type-Options', 'nosniff')
    # prevent some XSS from browser
    resp.setHeader('X-XSS-Protection', '1; mode=block')


@adapter(IPubBeforeCommit)
def beforeCommit(event):
    """
    Couple causes here:

    1. Lockout support
        check if user attempted to login to the site.
        If success, reset counter, if fail, tally it.

    """
    request = event.request

    if not ICastleLayer.providedBy(request):
        return

    site = api.portal.get()

    resp = request.response
    contentType = resp.getHeader('Content-Type')
    if site is None or contentType is None or not contentType.startswith('text/html'):
        return None

    # now, check user roles. If they have none, make sure to
    # throw an exception with message saying the user's account
    # is disabled
    user = api.user.get_current()
    if user.getId() is None:
        return
    if api.user.get_roles(user=user) == ['Authenticated']:
        # clear login cookies
        mt = api.portal.get_tool('portal_membership')
        mt.logoutUser(request)
        resp.redirect('%s/@@disabled-user' % site.absolute_url())

    session_manager = SessionManager(site, request, user)
    if not session_manager.has_session_id():
        # register new session with new id and storage
        session_manager.register()
    else:
        session = session_manager.get()
        if not session:
            session_manager.log({})
        else:
            if session_manager.expired(session):
                mt = api.portal.get_tool('portal_membership')
                mt.logoutUser(request)
                resp.expireCookie(session_manager.cookie_name)
                session_manager.delete()
                resp.redirect('%s/@@session-removed' % site.absolute_url())
            else:
                session_manager.log(session)
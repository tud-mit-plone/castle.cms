from Acquisition import aq_inner
from Acquisition import aq_parent
from borg.localrole.interfaces import IFactoryTempFolder
from castle.cms import cache
from castle.cms import theming
from castle.cms.interfaces import IDashboard
from plone import api
from plone.app.imaging.utils import getAllowedSizes
from plone.app.layout.navigation.defaultpage import getDefaultPage
from plone.dexterity.interfaces import IDexterityContainer
from plone.memoize.view import memoize
from plone.registry.interfaces import IRegistry
from plone.tiles.interfaces import ITileType
from plone.uuid.interfaces import IUUID
from Products.CMFCore.interfaces import ISiteRoot
from Products.CMFCore.interfaces._content import IFolderish
from Products.CMFPlone.interfaces import IPatternsSettings
from Products.CMFPlone.interfaces import IPloneSiteRoot
from Products.CMFPlone.patterns import PloneSettingsAdapter
from Products.CMFPlone.patterns import TinyMCESettingsGenerator
from zope.component import getUtility
from zope.interface import implements

import json


class CastleTinyMCESettingsGenerator(TinyMCESettingsGenerator):

    def get_tiny_config(self):
        config = super(CastleTinyMCESettingsGenerator, self).get_tiny_config()
        if 'paste' not in config['plugins']:
            config['plugins'] += 'paste'
        config['paste_data_images'] = True
        config['paste_as_text'] = True
        config['paste_word_valid_elements'] = "b,strong,i,em,h1,h2,h3,h4,ul,li"
        config['paste_retain_style_properties'] = ''
        config['paste_merge_formats'] = True
        content_css = config['content_css'].split(',')
        style_css = config['importcss_file_filter'].split(',')
        content_css.extend(style_css)
        config['content_css'] = ','.join(set(content_css))
        config['browser_spellcheck'] = True
        formats = config.get('formats')
        if isinstance(formats, list):
            config['style_formats'].extend(formats)
        return config


class CastleSettingsAdapter(PloneSettingsAdapter):
    """
    This adapter will handle all default plone settings.

    Right now, it only does tinymce
    """
    implements(IPatternsSettings)

    def __init__(self, context, request, field):
        super(CastleSettingsAdapter, self).__init__(context, request, field)
        self.site = api.portal.get()

    @property
    @memoize
    def registry(self):
        return getUtility(IRegistry)

    def get_available_slot_tiles(self):
        cache_key = '%s-slot-tiles' % '/'.join(self.site.getPhysicalPath()[1:])
        try:
            return cache.get(cache_key)
        except:
            pass

        available_tiles = self.registry.get('castle.slot_tiles')
        if not available_tiles:
            available_tiles = {
                'Structure': ['plone.app.standardtiles.rawhtml']
            }

        # otherwise, you're editing the value in the DB!!!!
        available_tiles = available_tiles.copy()

        for group_name, tile_ids in available_tiles.items():
            group = []
            for tile_id in tile_ids:
                tile = getUtility(ITileType, name=tile_id)
                group.append({
                    'id': tile_id,
                    'label': tile.title
                })
            available_tiles[group_name] = group
        cache.set(cache_key, available_tiles, 600)
        return available_tiles

    def tinymce(self):
        if api.user.is_anonymous():
            return {}
        generator = CastleTinyMCESettingsGenerator(self.context, self.request)
        settings = generator.settings

        folder = aq_inner(self.context)
        # Test if we are currently creating an Archetype object
        if IFactoryTempFolder.providedBy(aq_parent(folder)):
            folder = aq_parent(aq_parent(aq_parent(folder)))
        if not IFolderish.providedBy(folder):
            folder = aq_parent(folder)

        if IPloneSiteRoot.providedBy(folder):
            initial = None
        else:
            initial = IUUID(folder, None)
        current_path = folder.absolute_url()[len(generator.portal_url):]

        scales = []
        for name, info in sorted(getAllowedSizes().items(), key=lambda x: x[1][0]):
            scales.append({
                'part': name,
                'name': name,
                'label': '{} ({}x{})'.format(
                    name.capitalize(),
                    info[0],
                    info[1])
            })
        image_types = settings.image_objects or []
        folder_types = settings.contains_objects or []
        configuration = {
            'relatedItems': {
                'vocabularyUrl':
                    '%s/@@getVocabulary?name=plone.app.vocabularies.Catalog' % (
                        generator.portal_url)
            },
            'upload': {
                'initialFolder': initial,
                'currentPath': current_path,
                'baseUrl': generator.portal_url,
                'relativePath': '@@fileUpload',
                'uploadMultiple': False,
                'maxFiles': 1,
                'showTitle': False
            },
            'base_url': self.context.absolute_url(),
            'tiny': generator.get_tiny_config(),
            # This is for loading the languages on tinymce
            'loadingBaseUrl': '%s/++plone++static/components/tinymce-builded/js/tinymce' % generator.portal_url,  # noqa
            'prependToUrl': 'resolveuid/',
            'linkAttribute': 'UID',
            'prependToScalePart': '/@@images/image/',
            'folderTypes': folder_types,
            'imageTypes': image_types,
            'scales': scales
        }

        return {'data-pat-tinymce': json.dumps(configuration)}

    def __call__(self):
        data = super(CastleSettingsAdapter, self).__call__()

        if api.user.is_anonymous():
            return data

        folder = self.context
        if not IDexterityContainer.providedBy(folder):
            folder = aq_parent(folder)
        required_upload_fields = self.registry.get(
            'castle.required_file_upload_fields', []) or []
        data.update({
            'data-available-slots': json.dumps(self.get_available_slot_tiles()),
            'data-required-file-upload-fields': json.dumps(required_upload_fields),
            'data-google-maps-api-key': self.registry.get(
                'castle.google_maps_api_key', '') or '',
            'data-folder-url': folder.absolute_url()
        })

        show_tour = False
        user = api.user.get_current()
        viewed = user.getProperty('tours_viewed', [])
        if ('all' not in viewed and
                set(viewed) != set(['welcome', 'dashboard', 'foldercontents',
                                    'addcontentinitial', 'addcontentadd', 'editpage'])):
            show_tour = True

        if show_tour and not api.env.test_mode():
            data['data-show-tour'] = json.dumps({
                'viewed': viewed
            })

        folder = self.context
        if not ISiteRoot.providedBy(folder) and not IDexterityContainer.providedBy(folder):
            folder = aq_parent(folder)
        site_path = self.site.getPhysicalPath()
        folder_path = folder.getPhysicalPath()
        data['data-base-path'] = '/' + '/'.join(folder_path[len(site_path):])

        real_context = self.context
        if ISiteRoot.providedBy(real_context):
            # we're at site root but actually kind of want context front page
            try:
                real_context = real_context[getDefaultPage(real_context)]
            except (AttributeError, KeyError):
                pass
        if IDashboard.providedBy(real_context):
            real_context = self.site

        transform = theming.getTransform(real_context, self.request)
        if transform is not None:
            data['data-site-layout'] = transform.get_layout_name(real_context)

        data['data-site-default'] = getDefaultPage(self.site) or 'front-page'

        return data

from castle.cms.tiles.base import DisplayTypeTileMixin
from castle.cms.tiles.base import ContentTile
from castle.cms.tiles.content import IContentTileSchema
from castle.cms.tiles.views import BaseTileView
from castle.cms.tiles.views import TileViewsSource
from castle.cms.widgets import FocalPointSelectFieldWidget
from castle.cms.widgets import PreviewSelectFieldWidget
from plone.autoform import directives as form
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from z3c.form.browser.checkbox import CheckBoxFieldWidget
from zope import schema
from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary


DISPLAY_TYPE_KEY = 'existing'


class BasicView(BaseTileView):
    name = 'basic'
    preview = ''
    order = 0
    index = ViewPageTemplateFile('templates/existing/basic.pt')
    tile_name = DISPLAY_TYPE_KEY


class BackgroundImageView(BaseTileView):
    name = 'backgroundimage'
    preview = ''
    order = 1
    index = ViewPageTemplateFile('templates/existing/backgroundimage.pt')
    tile_name = DISPLAY_TYPE_KEY


class ExistingTile(ContentTile, DisplayTypeTileMixin):

    display_type_name = DISPLAY_TYPE_KEY
    display_type_default = 'basic'
    display_type_fallback_view = BasicView

    def joiner(self, val, joiner=', '):
        if not val:
            return ''
        if type(val) in (set, list, tuple):
            val = joiner.join(val)
        if isinstance(val, basestring) and '\n' in val:
            val = joiner.join(val.splitlines())
        return val


class IExistingTileSchema(IContentTileSchema):

    form.order_before(title='use_query')
    title = schema.TextLine(
        title=u'Title heading',
        description=u'Will be omitted if blank',
        required=False,
        default=u'')

    form.widget('display_fields', CheckBoxFieldWidget)
    display_fields = schema.Tuple(
        title=u'Display fields',
        description=u'Fields that should show from the content',
        default=(
            'title',
            'image',
            'description'
        ),
        value_type=schema.Choice(
            vocabulary=SimpleVocabulary([
                SimpleTerm('title', 'title', u'Title'),
                SimpleTerm('image', 'image', u'Image'),
                SimpleTerm('description', 'description', u'Overview/Summary'),
                SimpleTerm('date', 'date', u'Date'),
            ])
        )
    )

    truncate_count = schema.Int(
        title=u'Overview/Summary Truncate',
        description=u'Number of words to truncate the overview/summary to',
        required=False,
        default=18
    )

    image_display_type = schema.Choice(
        title=u'Image display type',
        description=u'Does not apply to all display types',
        required=True,
        default=u'landscape',
        vocabulary=SimpleVocabulary([
            SimpleTerm('landscape', 'landscape', u'Landscape'),
            SimpleTerm('portrait', 'portrait', u'Portrait'),
            SimpleTerm('square', 'square', u'Square')
        ])
    )

    display_type = schema.Choice(
        title=u"Display Type",
        vocabulary=SimpleVocabulary([
            SimpleTerm('basic', 'basic', u'Basic'),
            SimpleTerm('backgroundimage', 'backgroundimage', u'Background Image')
        ]),
        default='basic'
    )

    form.widget('display_type', PreviewSelectFieldWidget,
                tile_name=DISPLAY_TYPE_KEY)
    display_type = schema.Choice(
        title=u"Display Type",
        source=TileViewsSource(DISPLAY_TYPE_KEY),
        default='default'
    )

    form.widget(override_focal_point=FocalPointSelectFieldWidget)
    override_focal_point = schema.Text(
        title=u'Override Focal point',
        default=u'',
        required=False
    )

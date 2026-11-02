from django import template
from django.conf import settings

from orderpiqrApp.utils.build_id import get_build_id

register = template.Library()


@register.simple_tag
def build_static_prefix():
    """Static prefix carrying the current build id as a path segment.

    Use this for the scan page's ES-module tags instead of
    ``{% get_static_prefix %}``. Every module the tagged entry point imports is
    then fetched from the same build-scoped directory, because relative import
    specifiers resolve against the importing module's URL — which is what keeps
    a page's module graph on one single build. See
    ``orderpiqrApp.views.static_views`` for why a path segment and not a
    filename hash or a query string.
    """
    return f"{settings.STATIC_URL}b/{get_build_id()}/"

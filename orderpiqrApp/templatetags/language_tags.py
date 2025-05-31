from django import template
from django.conf import settings

register = template.Library()

@register.simple_tag
def get_native_language_name(lang_code):
    for code, name in settings.LANGUAGES:
        if code == lang_code:
            return name
    return lang_code  # fallback

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IntegrationsShopifyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations_shopify'
    verbose_name = _('Shopify integration')

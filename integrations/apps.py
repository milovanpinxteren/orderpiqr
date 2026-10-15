from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations'
    verbose_name = _('Integrations')

    def ready(self):
        # Import connectors so they self-register in the registry.
        from integrations.registry import autodiscover
        autodiscover()

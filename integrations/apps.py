from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations'
    verbose_name = 'Integrations'

    def ready(self):
        # Import connectors so they self-register in the registry.
        from integrations.registry import autodiscover
        autodiscover()

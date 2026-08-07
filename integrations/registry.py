"""Connector registry. Platform apps register their connector class with
@register_connector; the core looks them up by Connection.platform."""

from importlib import import_module

from django.apps import apps

_REGISTRY = {}


def register_connector(cls):
    """Class decorator: register a BaseConnector subclass by its platform."""
    if not getattr(cls, 'platform', None):
        raise ValueError(f"{cls.__name__} must define a 'platform' attribute")
    _REGISTRY[cls.platform] = cls
    return cls


def get_connector_class(platform):
    return _REGISTRY.get(platform)


def all_platforms():
    return dict(_REGISTRY)


def autodiscover():
    """Import a `connector` module from every installed integrations_* app so
    their @register_connector decorators run."""
    for app_config in apps.get_app_configs():
        if app_config.name.startswith('integrations_'):
            try:
                import_module(f'{app_config.name}.connector')
            except ModuleNotFoundError as exc:
                # Only swallow "no connector module", not import errors inside it.
                if exc.name != f'{app_config.name}.connector':
                    raise

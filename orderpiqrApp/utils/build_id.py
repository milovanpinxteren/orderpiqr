from django.contrib.staticfiles.storage import staticfiles_storage


def get_build_id():
    """Identifier for the client code currently being served.

    The manifest hash changes whenever any static asset changes, which is
    exactly when a long-lived scan page needs a reload — a Python-only deploy
    doesn't ask devices to refresh. Falls back to 'dev' when no collected
    manifest exists (local runserver), so dev pages never self-reload.
    """
    return getattr(staticfiles_storage, 'manifest_hash', '') or 'dev'

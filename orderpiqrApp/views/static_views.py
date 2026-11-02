"""Build-scoped serving of collected static files.

The scan page's ES-module graph is loaded from URLs that carry the current
build id as a *path* segment — ``/static/b/<build>/orderpiqrApp/js/...`` — and
this view is what answers them.

Why a path segment and not a hash on the filename or a ``?v=`` query:

* Hashed filenames are the thing that caused the 2026-10-11 shadow-module
  regression. Manifest storage rewrites the URL in a ``<script>`` tag but not
  the relative import specifiers *inside* a module, so hashed tags load a
  second, separate copy of the whole graph (see the comment above the module
  tags in templates/index.html). That rule stands: filenames stay unhashed.
* A query string does not propagate either. ``import './shortPick.js'`` from
  ``.../camera_page.js?v=abc`` resolves to ``.../shortPick.js`` with no query
  at all, so only the entry point would be versioned.
* A path segment *does* propagate, because relative specifiers resolve against
  the importing module's directory. Tag one entry point at
  ``/static/b/<build>/...`` and every module it imports is fetched from the
  same build-scoped directory, for free and with no list to maintain.

That is what makes the service worker's stale-while-revalidate cache correct
rather than merely fast: a page from build B can no longer be served build A's
modules out of a cache, because it never asks for A's URLs. Before this, the
first reload after any deploy mixed the two — new HTML requesting a module that
was new in the deploy (so: cache miss, fetched fresh) alongside modules the old
cache already held, which is how 2026-10-26 shipped a scan page whose
``shortPick.js`` imported ``declareShort`` from a ``camera_page.js`` that did
not export it yet.
"""
import mimetypes
import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.utils._os import safe_join
from django.views.decorators.http import require_safe

# A browser refuses an ES module outright when the response carries a non-JS
# content type, and mimetypes.guess_type answers for '.js' out of the Windows
# registry, where it can come back as 'text/plain'. Everything this view exists
# to serve is in here explicitly rather than guessed.
CONTENT_TYPES = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.map': 'application/json',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.woff': 'font/woff',
}


def _checked_path(path):
    """The request's static path, or 404 if it tries to leave the static root."""
    if not path or path.startswith('/') or '\\' in path or '..' in path.split('/'):
        raise Http404('Invalid static path')
    return path


def _resolve(path):
    """Absolute filesystem path of a collected static file, or None.

    STATIC_ROOT first, because in production that is the collected (and for CSS,
    post-processed) copy. The finders fallback is for the local runserver, where
    collectstatic has not necessarily run and STATIC_ROOT may be empty — without
    it, the scan page would 404 its whole module graph in development.
    """
    if settings.STATIC_ROOT:
        try:
            candidate = safe_join(settings.STATIC_ROOT, path)
        except (ValueError, SuspiciousFileOperation):
            raise Http404('Invalid static path')
        if os.path.isfile(candidate):
            return candidate
    return finders.find(path)


@require_safe
def build_scoped_static(request, build, path):
    """Serve ``path`` from the static root, immutably.

    ``build`` is deliberately unused: it is a cache key, not a lookup key.
    There is only ever one copy of a file on disk, and the segment's whole job
    is to make a new build's URLs distinct from the previous build's so that no
    cache — the service worker's or the browser's — can answer one with the
    other. Validating it against the current build would be actively wrong: a
    page loaded before a deploy must keep being able to fetch its own build's
    URLs rather than get a 404 mid-shift.
    """
    path = _checked_path(path)
    full_path = _resolve(path)
    if not full_path:
        raise Http404(path)

    extension = os.path.splitext(full_path)[1].lower()
    content_type = (CONTENT_TYPES.get(extension)
                    or mimetypes.guess_type(full_path)[0]
                    or 'application/octet-stream')
    response = FileResponse(open(full_path, 'rb'), content_type=content_type)
    # Safe precisely because the build id is in the URL: these bytes cannot
    # change without the URL changing too.
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response

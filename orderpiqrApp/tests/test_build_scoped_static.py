"""Build-scoped static serving, and the coherence property it exists for.

The bug these guard against: on the first reload after a deploy the service
worker served a page from the new build a module graph half-assembled from the
old build's cache. A module that was new in the deploy missed the old cache and
came down fresh, so on 2026-10-26 a new shortPick.js imported `declareShort`
from a camera_page.js that did not export it yet, and the scan page died with a
SyntaxError for seven pickers across two days.

The fix is a URL property, not a runtime negotiation: every module is fetched
from a directory named after the build, so two builds can never share a cache
key. These tests pin that property down at the three places it has to hold —
the prefix tag, the page's tags, and the service worker's pre-cache list.
"""
import posixpath
import re

from django.test import TestCase
from django.urls import reverse

from orderpiqrApp.utils.build_id import get_build_id


class BuildStaticPrefixTagTests(TestCase):
    def test_prefix_contains_the_build_id_as_a_path_segment(self):
        from orderpiqrApp.templatetags.build_tags import build_static_prefix
        prefix = build_static_prefix()
        self.assertEqual(prefix, '/static/b/%s/' % get_build_id())

    def test_prefix_ends_in_a_slash(self):
        # Templates concatenate a bare relative path onto this; a missing
        # slash would silently produce '/static/b/abcorderpiqrApp/js/...'.
        from orderpiqrApp.templatetags.build_tags import build_static_prefix
        self.assertTrue(build_static_prefix().endswith('/'))

    def test_build_id_is_not_a_query_string(self):
        # A query string is the obvious-looking fix that does not work:
        # relative import specifiers resolve without it, so only the entry
        # point would be versioned and the graph would still mix builds.
        from orderpiqrApp.templatetags.build_tags import build_static_prefix
        self.assertNotIn('?', build_static_prefix())


class BuildScopedStaticViewTests(TestCase):
    def url(self, path, build=None):
        return '/static/b/%s/%s' % (build or get_build_id(), path)

    def test_serves_a_module_from_the_graph(self):
        response = self.client.get(self.url('orderpiqrApp/js/camera_page.js'))
        self.assertEqual(response.status_code, 200)

    def test_javascript_content_type(self):
        # A browser refuses an ES module outright on a non-JS content type,
        # and mimetypes answers for '.js' out of the Windows registry where it
        # can come back as text/plain. Hence the explicit map in the view.
        response = self.client.get(self.url('orderpiqrApp/js/camera_page.js'))
        self.assertEqual(response['Content-Type'], 'text/javascript')

    def test_immutable_cache_control(self):
        response = self.client.get(self.url('orderpiqrApp/js/camera_page.js'))
        self.assertIn('immutable', response['Cache-Control'])
        self.assertIn('max-age=31536000', response['Cache-Control'])

    def test_an_unknown_build_segment_still_serves(self):
        # Load-bearing: a page loaded BEFORE a deploy must keep being able to
        # fetch its own build's URLs. Validating the segment against the
        # current build would 404 a picker's open page mid-shift.
        response = self.client.get(self.url('orderpiqrApp/js/camera_page.js',
                                            build='some-older-build'))
        self.assertEqual(response.status_code, 200)

    def test_missing_file_is_404(self):
        response = self.client.get(self.url('orderpiqrApp/js/not_a_real_module.js'))
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_is_refused(self):
        for path in ('../../manage.py', 'orderpiqrApp/../../../manage.py'):
            response = self.client.get(self.url(path))
            self.assertIn(response.status_code, (301, 400, 404),
                          'traversal %r was served' % path)

    def test_post_is_rejected(self):
        response = self.client.post(self.url('orderpiqrApp/js/camera_page.js'))
        self.assertEqual(response.status_code, 405)

    def test_route_is_reversible(self):
        self.assertEqual(
            reverse('build-scoped-static',
                    kwargs={'build': 'abc', 'path': 'orderpiqrApp/js/camera_page.js'}),
            '/static/b/abc/orderpiqrApp/js/camera_page.js')


class ModuleGraphCoherenceTests(TestCase):
    """The page and the service worker must agree, URL for URL."""

    MODULES = [
        'qrScanner.js', 'notifications.js', 'orderImportance.js',
        'picklistHandler.js', 'domUpdater.js', 'scanEventReporter.js',
        'manualOverride.js', 'picklistSearch.js', 'syncBadge.js',
        'shortPick.js', 'camera_page.js',
    ]

    def service_worker_body(self):
        return self.client.get('/serviceWorker.js').content.decode('utf-8')

    def test_service_worker_precaches_the_graph_build_scoped(self):
        body = self.service_worker_body()
        self.assertIn("MODULE_PREFIX = '/static/b/%s/'" % get_build_id(), body)
        for module in self.MODULES:
            self.assertIn("MODULE_PREFIX + 'orderpiqrApp/js/%s'" % module, body)

    def test_import_only_modules_are_build_scoped_too(self):
        # fingerprint.js, pickOutbox.js, appUpdater.js and shortReasons.js are
        # reached only by an import, so nothing but this list ever names them —
        # and they are exactly the ones a half-stale graph breaks on.
        body = self.service_worker_body()
        for module in ('fingerprint.js', 'pickOutbox.js', 'appUpdater.js',
                       'shortReasons.js'):
            self.assertIn("MODULE_PREFIX + 'orderpiqrApp/js/%s'" % module, body)

    def test_no_module_is_precached_under_the_bare_static_prefix(self):
        # The regression this whole change exists to prevent: a module cached
        # under a URL that two builds share.
        body = self.service_worker_body()
        for module in self.MODULES:
            self.assertNotIn("STATIC_PREFIX + 'orderpiqrApp/js/%s'" % module, body)

    def test_every_module_in_the_graph_is_served_and_precached(self):
        """Walk the real import graph instead of trusting a hand-kept list.

        Both halves matter and both have failed in production: a module that
        the graph imports but the pre-cache list omits is missing offline, and
        a module the page can't fetch at all is a dead scan page. Walking the
        imports means adding a module to the graph can't silently skip either.
        """
        body = self.service_worker_body()
        entry_points = ['orderpiqrApp/js/camera_page.js',
                        'orderpiqrApp/js/syncBadge.js']
        seen, queue = set(), list(entry_points)
        while queue:
            module = queue.pop()
            if module in seen:
                continue
            seen.add(module)

            url = '/static/b/%s/%s' % (get_build_id(), module)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200,
                             '%s is in the import graph but not served' % module)
            self.assertIn("MODULE_PREFIX + '%s'" % module, body,
                          '%s is imported but never pre-cached' % module)

            source = b''.join(response.streaming_content).decode('utf-8')
            directory = posixpath.dirname(module)
            for specifier in re.findall(
                    r'(?:^|\n)\s*(?:import|export)[^\n;]*?from\s+[\'"](\./[^\'"]+)[\'"]',
                    source):
                queue.append(posixpath.normpath(posixpath.join(directory, specifier)))

        # Sanity floor: if the regex ever stops matching, the loop above would
        # pass by visiting nothing at all.
        self.assertGreaterEqual(len(seen), 10,
                                'only walked %d modules — did import parsing break?' % len(seen))

    def test_classic_scripts_are_precached_hashed_like_the_page_tags_them(self):
        # index.html tags these with {% static %}, so pre-caching them
        # unhashed left the entry under a URL nothing asks for — an offline
        # reload came up without its own error reporter.
        body = self.service_worker_body()
        for name in ('clientHealth', 'installPrompt'):
            self.assertNotIn("STATIC_PREFIX + 'orderpiqrApp/js/%s.js'" % name, body)
            self.assertIn('orderpiqrApp/js/%s' % name, body)

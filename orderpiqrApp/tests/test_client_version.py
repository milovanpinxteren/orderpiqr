"""The client-version endpoint the long-lived scan page polls to decide when
to reload itself for a new deploy."""
from django.test import TestCase

from orderpiqrApp.utils.build_id import get_build_id


class ClientVersionTests(TestCase):
    def test_returns_build_id_without_auth(self):
        response = self.client.get('/orderpiqr/client-version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'buildId': get_build_id()})

    def test_build_id_is_nonempty(self):
        # Without a collected manifest (tests, runserver) it falls back to
        # 'dev', which the client treats as "never self-reload".
        self.assertTrue(get_build_id())

    def test_post_is_rejected(self):
        response = self.client.post('/orderpiqr/client-version')
        self.assertEqual(response.status_code, 405)

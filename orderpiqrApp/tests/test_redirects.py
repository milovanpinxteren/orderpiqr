"""Shorthand-URL redirects: /manage/... must reach the manage portal, not 404."""
from django.test import TestCase


class ManageShorthandRedirectTests(TestCase):
    def test_manage_path_redirects_to_orderpiqr_prefix(self):
        response = self.client.get('/manage/products/import/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/orderpiqr/manage/products/import/')

    def test_manage_root_redirects(self):
        response = self.client.get('/manage/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/orderpiqr/manage/')

    def test_query_string_preserved(self):
        response = self.client.get('/manage/products/?page=2')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/orderpiqr/manage/products/?page=2')

    def test_full_chain_lands_on_login_not_404(self):
        response = self.client.get('/manage/products/import/', follow=True)
        self.assertEqual(response.status_code, 200)

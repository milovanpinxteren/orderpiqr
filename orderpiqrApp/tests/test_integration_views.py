"""Portal pages for integrations and API tokens: auth, customer scoping,
pairing key issuance and token self-service."""
import hashlib

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import activate

from drf_hashed_token.models import HashedToken
from integrations.models import Connection
from integrations_woocommerce.models import PairingToken, WooCommerceStore
from orderpiqrApp.models import Customer, UserProfile


class PortalTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='boss', password='secret123')

        self.other_customer = Customer.objects.create(name='Other company')

    def make_connection(self, customer=None, **kwargs):
        kwargs.setdefault('platform', 'woocommerce')
        kwargs.setdefault('status', 'active')
        kwargs.setdefault('name', 'Test Store')
        connection = Connection.objects.create(
            customer=customer or self.customer, **kwargs)
        WooCommerceStore.objects.create(
            connection=connection, store_url='https://shop.example.com')
        return connection


class IntegrationsListTests(PortalTestCase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('manage_integrations'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_requires_company_admin(self):
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        picker = User.objects.create_user(username='picker', password='secret123')
        picker.groups.add(picker_group)
        UserProfile.objects.create(user=picker, customer=self.customer)
        self.client.login(username='picker', password='secret123')
        response = self.client.get(reverse('manage_integrations'))
        self.assertEqual(response.status_code, 403)

    def test_lists_own_connections_only(self):
        self.make_connection(name='Mine')
        self.make_connection(customer=self.other_customer, name='Theirs')
        response = self.client.get(reverse('manage_integrations'))
        self.assertContains(response, 'Mine')
        self.assertNotContains(response, 'Theirs')

    def test_disconnected_connections_are_hidden(self):
        self.make_connection(name='Old store', status='disconnected')
        response = self.client.get(reverse('manage_integrations'))
        self.assertNotContains(response, 'Old store')


class PairingKeyTests(PortalTestCase):
    def test_connect_button_issues_single_use_key(self):
        response = self.client.post(
            reverse('manage_integrations_connect_woocommerce'))
        self.assertEqual(response.status_code, 200)
        raw_key = response.context['pairing_key']
        self.assertTrue(raw_key.startswith('opqpk_'))
        self.assertContains(response, raw_key)

        token = PairingToken.find(raw_key)
        self.assertIsNotNone(token)
        self.assertEqual(token.customer, self.customer)
        self.assertFalse(token.is_used)
        self.assertFalse(token.is_expired)
        # Only the hash is stored
        self.assertEqual(token.token_hash,
                         hashlib.sha256(raw_key.encode()).hexdigest())

    def test_get_is_not_allowed(self):
        response = self.client.get(
            reverse('manage_integrations_connect_woocommerce'))
        self.assertEqual(response.status_code, 405)


class ConnectionActionTests(PortalTestCase):
    def test_pause_and_resume(self):
        connection = self.make_connection()
        url = reverse('manage_integration_toggle', args=[connection.pk])
        self.client.post(url)
        connection.refresh_from_db()
        self.assertEqual(connection.status, 'paused')
        self.client.post(url)
        connection.refresh_from_db()
        self.assertEqual(connection.status, 'active')

    def test_disconnect(self):
        connection = self.make_connection()
        self.client.post(reverse('manage_integration_disconnect',
                                 args=[connection.pk]))
        connection.refresh_from_db()
        self.assertEqual(connection.status, 'disconnected')

    def test_cannot_touch_other_customers_connection(self):
        foreign = self.make_connection(customer=self.other_customer)
        response = self.client.post(
            reverse('manage_integration_toggle', args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, 'active')

    def test_config_save(self):
        connection = self.make_connection()
        url = reverse('manage_integration_config', args=[connection.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(url, {
            'fulfill_on_complete': 'on',
            'fulfill_status': 'custom-shipped',
        })
        self.assertEqual(response.status_code, 302)
        connection.refresh_from_db()
        config = connection.get_config()
        self.assertFalse(config['auto_queue'])  # unchecked checkbox
        self.assertTrue(config['fulfill_on_complete'])
        self.assertEqual(config['fulfill_status'], 'custom-shipped')

    def test_config_default_fulfill_status_is_not_persisted(self):
        connection = self.make_connection()
        url = reverse('manage_integration_config', args=[connection.pk])
        self.client.post(url, {'auto_queue': 'on', 'fulfill_status': ''})
        connection.refresh_from_db()
        self.assertNotIn('fulfill_status', connection.config)
        self.assertEqual(connection.get_config()['fulfill_status'], 'completed')


class ApiTokenPageTests(PortalTestCase):
    url_name = 'manage_api_tokens'

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 302)

    def test_create_shows_token_once_and_stores_hash(self):
        response = self.client.post(reverse(self.url_name), {
            'action': 'create', 'stage': 'LIVE'})
        self.assertEqual(response.status_code, 200)
        raw = response.context['new_token']
        self.assertTrue(raw.startswith('Live_'))

        token = HashedToken.objects.get(user=self.admin)
        self.assertTrue(token.check_token(raw.split('_', 1)[1]))
        # A fresh GET no longer shows the token
        response = self.client.get(reverse(self.url_name))
        self.assertIsNone(response.context['new_token'])
        self.assertNotContains(response, raw)

    def test_create_replaces_existing_token_of_same_stage(self):
        self.client.post(reverse(self.url_name), {'action': 'create', 'stage': 'LIVE'})
        first_hash = HashedToken.objects.get(user=self.admin).key_hash
        self.client.post(reverse(self.url_name), {'action': 'create', 'stage': 'LIVE'})
        tokens = HashedToken.objects.filter(user=self.admin)
        self.assertEqual(tokens.count(), 1)
        self.assertNotEqual(tokens.get().key_hash, first_hash)

    def test_revoke(self):
        self.client.post(reverse(self.url_name), {'action': 'create', 'stage': 'LIVE'})
        key_hash = HashedToken.objects.get(user=self.admin).key_hash
        self.client.post(reverse(self.url_name), {
            'action': 'revoke', 'key_hash': key_hash})
        self.assertFalse(HashedToken.objects.filter(key_hash=key_hash).exists())

    def test_cannot_revoke_other_customers_token(self):
        outsider = User.objects.create_user(username='outsider', password='x')
        UserProfile.objects.create(user=outsider, customer=self.other_customer)
        raw, key_hash = HashedToken.generate_token()
        HashedToken.objects.create(user=outsider, key_hash=key_hash, stage='LIVE')

        self.client.post(reverse(self.url_name), {
            'action': 'revoke', 'key_hash': key_hash})
        self.assertTrue(HashedToken.objects.filter(key_hash=key_hash).exists())

    def test_lists_only_customer_tokens(self):
        outsider = User.objects.create_user(username='outsider', password='x')
        UserProfile.objects.create(user=outsider, customer=self.other_customer)
        _, key_hash = HashedToken.generate_token()
        HashedToken.objects.create(user=outsider, key_hash=key_hash, stage='LIVE')

        response = self.client.get(reverse(self.url_name))
        self.assertEqual(list(response.context['tokens']), [])

"""The self-install onboarding path: can the merchant actually get in?

Installing from the App Store provisions a companyadmin and an orderpicker
account with random passwords nobody sees. The embedded console could set the
picker's password, but the admin account had neither a known password nor an
email address to reset it to — so everything outside this one panel (products,
picker login QR codes, scan health, settings) was shut to every merchant who
installed from the App Store. Three real shops sat in that state for weeks
with their catalogs syncing and no human ever logged in.
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from integrations.models import Connection
from integrations_shopify import services
from integrations_shopify.emails import send_welcome_email
from integrations_shopify.models import ShopifyShop
from orderpiqrApp.models import Customer, UserProfile


class ProvisioningTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='companyadmin')
        Group.objects.get_or_create(name='orderpicker')

    def test_provision_creates_both_accounts(self):
        shop, created = services.provision_shop('newshop.myshopify.com')
        self.assertTrue(created)
        customer = shop.connection.customer
        usernames = set(User.objects
                        .filter(userprofile__customer=customer)
                        .values_list('username', flat=True))
        self.assertEqual(usernames, {'newshop_admin', 'newshop_picker'})
        self.assertTrue(shop.connection.auto_provisioned)

    def test_backfill_gives_the_accounts_a_resettable_address(self):
        shop, _ = services.provision_shop('newshop.myshopify.com')
        self.assertEqual(
            list(User.objects
                 .filter(userprofile__customer=shop.connection.customer)
                 .values_list('email', flat=True)),
            ['', ''])

        shop.shop_email = 'owner@newshop.example'
        shop.save(update_fields=['shop_email'])
        updated = services.backfill_user_emails(shop)

        self.assertEqual(updated, 2)
        for user in User.objects.filter(userprofile__customer=shop.connection.customer):
            self.assertEqual(user.email, 'owner@newshop.example')

    def test_backfill_never_overwrites_a_real_address(self):
        shop, _ = services.provision_shop('newshop.myshopify.com')
        admin = User.objects.get(username='newshop_admin')
        admin.email = 'bookkeeping@newshop.example'
        admin.save(update_fields=['email'])

        shop.shop_email = 'owner@newshop.example'
        shop.save(update_fields=['shop_email'])
        services.backfill_user_emails(shop)

        admin.refresh_from_db()
        self.assertEqual(admin.email, 'bookkeeping@newshop.example')

    def test_backfill_skips_a_linked_account(self):
        """A shop linked to a pre-existing OrderPiqr account must not have
        that company's user addresses rewritten to the shop's."""
        shop, _ = services.provision_shop('newshop.myshopify.com')
        shop.connection.auto_provisioned = False
        shop.connection.save(update_fields=['auto_provisioned'])
        shop.shop_email = 'owner@newshop.example'
        shop.save(update_fields=['shop_email'])

        self.assertEqual(services.backfill_user_emails(shop), 0)


class WelcomeEmailTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='companyadmin')
        Group.objects.get_or_create(name='orderpicker')
        self.shop, _ = services.provision_shop('newshop.myshopify.com')
        self.shop.shop_email = 'owner@newshop.example'
        self.shop.shop_name = 'New Shop'
        self.shop.save(update_fields=['shop_email', 'shop_name'])

    def test_welcome_email_carries_username_and_set_password_link(self):
        self.assertTrue(send_welcome_email(self.shop))

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['owner@newshop.example'])
        self.assertIn('New Shop', message.subject)
        self.assertIn('newshop_admin', message.body)
        self.assertIn('/password-reset-confirm/', message.body)

    def test_the_link_actually_sets_a_password(self):
        send_welcome_email(self.shop)
        url = next(line.strip() for line in mail.outbox[0].body.splitlines()
                   if '/password-reset-confirm/' in line)

        # Django's reset view swaps the token for a session-bound URL first.
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(response.redirect_chain[-1][0] if
                                    response.redirect_chain else url, {
            'new_password1': 'a-real-password-9',
            'new_password2': 'a-real-password-9',
        })
        self.assertIn(response.status_code, (200, 302))
        admin = User.objects.get(username='newshop_admin')
        self.assertTrue(admin.check_password('a-real-password-9'))

    def test_only_sent_once(self):
        self.assertTrue(send_welcome_email(self.shop))
        self.assertFalse(send_welcome_email(self.shop))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(self.shop.welcome_email_sent_at)

    def test_a_linked_account_is_never_mailed(self):
        """House of Beers has run on OrderPiqr for months with their own
        account; a "set your admin password" mail would be both wrong and
        alarming."""
        self.shop.connection.auto_provisioned = False
        self.shop.connection.save(update_fields=['auto_provisioned'])
        self.assertFalse(send_welcome_email(self.shop))
        self.assertEqual(len(mail.outbox), 0)

    def test_no_shop_email_means_no_send(self):
        self.shop.shop_email = ''
        self.shop.save(update_fields=['shop_email'])
        self.assertFalse(send_welcome_email(self.shop))
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_does_not_mark_as_sent(self):
        """activate_shop runs while the merchant waits on the console; a dead
        mail server must not break it, but must not swallow the mail either."""
        with patch('integrations_shopify.emails.EmailMultiAlternatives.send',
                   side_effect=OSError('connection refused')):
            self.assertFalse(send_welcome_email(self.shop))
        self.shop.refresh_from_db()
        self.assertIsNone(self.shop.welcome_email_sent_at)


class AdminPasswordEndpointTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='companyadmin')
        Group.objects.get_or_create(name='orderpicker')
        self.shop, _ = services.provision_shop('newshop.myshopify.com')

    def post(self, body):
        with patch('integrations_shopify.views._authenticated_shop',
                   return_value=self.shop):
            return self.client.post('/shopify/api/admin-password/',
                                    json.dumps(body),
                                    content_type='application/json')

    def test_sets_the_admin_password(self):
        response = self.post({'password': 'a-real-password-9'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['username'], 'newshop_admin')
        admin = User.objects.get(username='newshop_admin')
        self.assertTrue(admin.check_password('a-real-password-9'))

    def test_short_password_rejected(self):
        response = self.post({'password': 'short'})
        self.assertEqual(response.status_code, 400)

    def test_refused_for_a_linked_account(self):
        self.shop.connection.auto_provisioned = False
        self.shop.connection.save(update_fields=['auto_provisioned'])
        response = self.post({'password': 'a-real-password-9'})
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_is_rejected(self):
        response = self.client.post('/shopify/api/admin-password/',
                                    json.dumps({'password': 'a-real-password-9'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_status_reports_the_admin_account(self):
        with patch('integrations_shopify.views._authenticated_shop',
                   return_value=self.shop), \
             patch('integrations_shopify.services.check_subscription',
                   return_value=False):
            response = self.client.get('/shopify/api/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['admin_username'], 'newshop_admin')

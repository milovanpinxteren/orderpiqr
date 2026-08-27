"""Tests for the cached Managed Pricing subscription check."""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from integrations.models import Connection
from integrations_shopify.models import ShopifyShop
from integrations_shopify.services import check_subscription
from orderpiqrApp.models import Customer


def graphql_result(subs):
    return {'currentAppInstallation': {'activeSubscriptions': subs}}


class CheckSubscriptionTests(TestCase):
    def setUp(self):
        customer = Customer.objects.create(name='Test shop')
        connection = Connection.objects.create(
            customer=customer, platform='shopify', status='active')
        self.shop = ShopifyShop.objects.create(
            connection=connection, shop_domain='test.myshopify.com')

    def check(self, graphql_return=None, force=False, side_effect=None):
        with patch('integrations_shopify.services.ShopifyClient') as cls:
            client = cls.return_value
            if side_effect:
                client.graphql.side_effect = side_effect
            else:
                client.graphql.return_value = graphql_return
            result = check_subscription(self.shop, force=force)
        self.shop.refresh_from_db()
        return result

    def test_active_subscription(self):
        self.assertTrue(self.check(graphql_result(
            [{'name': 'Standard', 'status': 'ACTIVE'}])))
        self.assertEqual(self.shop.subscription_status, 'active')
        self.assertEqual(self.shop.subscription_plan, 'Standard')

    def test_no_subscription(self):
        self.assertFalse(self.check(graphql_result([])))
        self.assertEqual(self.shop.subscription_status, 'none')

    def test_recent_check_is_cached(self):
        self.shop.subscription_status = 'active'
        self.shop.subscription_checked_at = timezone.now()
        self.shop.save()
        with patch('integrations_shopify.services.ShopifyClient') as cls:
            self.assertTrue(check_subscription(self.shop))
            cls.assert_not_called()

    def test_api_failure_keeps_last_state(self):
        self.shop.subscription_status = 'active'
        self.shop.save()
        self.assertTrue(self.check(side_effect=RuntimeError('boom'), force=True))
        self.assertEqual(self.shop.subscription_status, 'active')

"""Per-token rate limiting for hashed-API-token traffic. Interactive
JWT/session requests must remain unthrottled."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from api.throttling import HashedTokenRateThrottle
from drf_hashed_token.models import HashedToken
from orderpiqrApp.models import Customer, UserProfile

LOW_RATE = {'hashed_token': '3/min'}


def make_token(user):
    raw_token, key_hash = HashedToken.generate_token()
    token = HashedToken.objects.create(user=user, key_hash=key_hash, stage='LIVE')
    return f"{token.get_stage_display()}_{raw_token}", token


class HashedTokenThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='hfportal', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)
        self.raw_token, self.token = make_token(self.user)
        self.client = APIClient()

    def get_orders(self, token=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token or self.raw_token}')
        return client.get('/api/orders/')

    def test_token_requests_are_throttled(self):
        with patch.object(HashedTokenRateThrottle, 'THROTTLE_RATES', LOW_RATE):
            for _ in range(3):
                self.assertEqual(self.get_orders().status_code, 200)
            response = self.get_orders()
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response.headers)

    def test_upsert_endpoint_is_covered(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.raw_token}')
        with patch.object(HashedTokenRateThrottle, 'THROTTLE_RATES', LOW_RATE):
            for _ in range(3):
                client.post('/api/orders/upsert/',
                            {'orders': [{'order_code': 'X', 'lines': []}]},
                            format='json')
            response = client.post(
                '/api/orders/upsert/',
                {'orders': [{'order_code': 'X', 'lines': []}]}, format='json')
        self.assertEqual(response.status_code, 429)

    def test_tokens_have_separate_buckets(self):
        other_user = User.objects.create_user(username='other', password='x')
        UserProfile.objects.create(user=other_user, customer=self.customer)
        other_raw, _ = make_token(other_user)
        with patch.object(HashedTokenRateThrottle, 'THROTTLE_RATES', LOW_RATE):
            for _ in range(3):
                self.assertEqual(self.get_orders().status_code, 200)
            self.assertEqual(self.get_orders().status_code, 429)
            self.assertEqual(self.get_orders(token=other_raw).status_code, 200)

    def test_session_auth_is_not_throttled(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        with patch.object(HashedTokenRateThrottle, 'THROTTLE_RATES', LOW_RATE):
            for _ in range(5):
                response = client.get('/api/orders/')
                self.assertEqual(response.status_code, 200)

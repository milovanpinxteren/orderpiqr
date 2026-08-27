from django.db import models
from django.utils import timezone

from integrations.crypto import decrypt, encrypt
from integrations.models import Connection


class ShopifyShop(models.Model):
    """Shopify-specific half of a Connection: shop identity + credentials.

    Tokens are stored encrypted (see integrations.crypto). Access tokens are
    the expiring offline kind (~60 min) obtained via session-token exchange;
    they are refreshed on demand by the client."""

    connection = models.OneToOneField(Connection, on_delete=models.CASCADE, related_name='shopify_shop')
    shop_domain = models.CharField(max_length=255, unique=True)  # foo.myshopify.com
    encrypted_access_token = models.TextField(blank=True, default='')
    encrypted_refresh_token = models.TextField(blank=True, default='')
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.TextField(blank=True, default='')
    shop_name = models.CharField(max_length=255, blank=True, default='')
    shop_email = models.CharField(max_length=255, blank=True, default='')
    installed_at = models.DateTimeField(auto_now_add=True)
    uninstalled_at = models.DateTimeField(null=True, blank=True)
    # Cursor for the reconciliation poll.
    last_synced_at = models.DateTimeField(null=True, blank=True)
    # Managed Pricing subscription state, cached from GraphQL:
    # '' = never checked, 'active' = active or trialing, 'none' = no subscription.
    subscription_status = models.CharField(max_length=20, blank=True, default='')
    subscription_plan = models.CharField(max_length=100, blank=True, default='')
    subscription_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Shopify shop'
        verbose_name_plural = 'Shopify shops'

    def __str__(self):
        return self.shop_domain

    @property
    def access_token(self):
        return decrypt(self.encrypted_access_token)

    @access_token.setter
    def access_token(self, value):
        self.encrypted_access_token = encrypt(value or '')

    @property
    def refresh_token(self):
        return decrypt(self.encrypted_refresh_token)

    @refresh_token.setter
    def refresh_token(self, value):
        self.encrypted_refresh_token = encrypt(value or '')

    @property
    def token_expired(self):
        if not self.token_expires_at:
            return False
        # Refresh slightly early to avoid mid-request expiry.
        return self.token_expires_at <= timezone.now() + timezone.timedelta(minutes=5)

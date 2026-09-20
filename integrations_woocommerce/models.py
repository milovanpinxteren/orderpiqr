import hashlib
import secrets

from django.db import models
from django.utils import timezone

from integrations.crypto import decrypt, encrypt
from integrations.models import Connection
from orderpiqrApp.models import Customer

PAIRING_TOKEN_TTL = timezone.timedelta(hours=24)


class WooCommerceStore(models.Model):
    """WooCommerce-specific half of a Connection: store identity + REST API
    credentials. Keys are stored encrypted (see integrations.crypto).

    The plugin authenticates itself towards us with a bearer token issued at
    connect time; only its sha256 hash is stored."""

    connection = models.OneToOneField(Connection, on_delete=models.CASCADE,
                                      related_name='woocommerce_store')
    store_url = models.CharField(max_length=255)  # https://shop.example.com
    store_name = models.CharField(max_length=255, blank=True, default='')
    encrypted_consumer_key = models.TextField(blank=True, default='')
    encrypted_consumer_secret = models.TextField(blank=True, default='')
    # Per-connection secret WooCommerce signs webhook deliveries with.
    webhook_secret = models.CharField(max_length=64, blank=True, default='')
    # sha256 of the token the plugin uses for status/disconnect calls.
    plugin_token_hash = models.CharField(max_length=64, blank=True, default='')
    wordpress_version = models.CharField(max_length=32, blank=True, default='')
    woocommerce_version = models.CharField(max_length=32, blank=True, default='')
    plugin_version = models.CharField(max_length=32, blank=True, default='')
    # Ids of the webhooks we registered in the store (for cleanup).
    webhook_ids = models.JSONField(default=list, blank=True)
    # Cursor for the reconciliation poll.
    last_poll_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'WooCommerce store'
        verbose_name_plural = 'WooCommerce stores'

    def __str__(self):
        return self.store_url

    @property
    def consumer_key(self):
        return decrypt(self.encrypted_consumer_key)

    @consumer_key.setter
    def consumer_key(self, value):
        self.encrypted_consumer_key = encrypt(value or '')

    @property
    def consumer_secret(self):
        return decrypt(self.encrypted_consumer_secret)

    @consumer_secret.setter
    def consumer_secret(self, value):
        self.encrypted_consumer_secret = encrypt(value or '')

    @staticmethod
    def generate_plugin_token():
        """Returns (raw_token, sha256_hash). The raw token is shown to the
        plugin exactly once, at connect time."""
        raw = f"opqpt_{secrets.token_hex(32)}"
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    def check_plugin_token(self, raw_token):
        if not self.plugin_token_hash or not raw_token:
            return False
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        return secrets.compare_digest(self.plugin_token_hash, digest)


class PairingToken(models.Model):
    """Single-use key created in the merchant portal and pasted into the
    WordPress plugin; pairs a store with a Customer. Only the hash is stored;
    the raw key is shown once."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
                                 related_name='woocommerce_pairing_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Pairing token'
        verbose_name_plural = 'Pairing tokens'

    def __str__(self):
        return f"Pairing token for {self.customer.name} ({'used' if self.used_at else 'open'})"

    @classmethod
    def issue(cls, customer):
        """Create a token for `customer`; returns (raw_key, instance)."""
        raw = f"opqpk_{secrets.token_hex(16)}"
        token = cls.objects.create(
            customer=customer,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + PAIRING_TOKEN_TTL,
        )
        return raw, token

    @classmethod
    def find(cls, raw_key):
        if not raw_key:
            return None
        digest = hashlib.sha256(str(raw_key).encode()).hexdigest()
        return cls.objects.filter(token_hash=digest).select_related('customer').first()

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def is_used(self):
        return self.used_at is not None

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])

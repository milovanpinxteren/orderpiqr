from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from orderpiqrApp.models import Customer, Order, Product


class Connection(models.Model):
    """A link between a Customer and an external sales platform.

    Platform-specific credentials live on child models in the platform app
    (e.g. integrations_shopify.ShopifyShop has a OneToOne to Connection).
    """

    PLATFORM_CHOICES = [
        ('shopify', 'Shopify'),
        ('woocommerce', 'WooCommerce'),
        ('bol', 'Bol.com'),
    ]

    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('active', _('Active')),
        ('paused', _('Paused')),
        ('disconnected', _('Disconnected')),
    ]

    connection_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='connections')
    platform = models.CharField(max_length=32, choices=PLATFORM_CHOICES)
    name = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    # True while this connection's Customer was auto-created at install time
    # and hasn't been linked to a pre-existing account.
    auto_provisioned = models.BooleanField(default=False)
    # Sync behaviour; merged over connector defaults, see get_config().
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Connection")
        verbose_name_plural = _("Connections")

    def __str__(self):
        return f"{self.get_platform_display()} – {self.name or self.customer.name}"

    # Platform-agnostic defaults; connectors may extend via config_defaults.
    DEFAULT_CONFIG = {
        # Which external identifier is matched against Product.code, in order.
        'identifier_chain': ['barcode', 'sku'],
        # auto_create | hold | skip
        'unknown_product_policy': 'auto_create',
        # Imported orders go straight into the picking queue (else draft).
        'auto_queue': True,
        'fulfill_on_complete': True,
        'notify_customer': True,
        'archive_on_complete': False,
        # hold = only fulfill when every line was picked
        'partial_fulfillment': 'hold',
        # off | push (OrderPiqr -> platform)
        'inventory_sync': 'off',
    }

    def get_config(self):
        from integrations.registry import get_connector_class
        merged = dict(self.DEFAULT_CONFIG)
        connector_cls = get_connector_class(self.platform)
        if connector_cls is not None:
            merged.update(connector_cls.config_defaults)
        merged.update(self.config or {})
        return merged

    def get_connector(self):
        from integrations.registry import get_connector_class
        connector_cls = get_connector_class(self.platform)
        if connector_cls is None:
            raise LookupError(f"No connector registered for platform '{self.platform}'")
        return connector_cls(self)


class WebhookInbox(models.Model):
    """Raw inbound events. Webhook views only verify, insert and return 200;
    poll-based connectors (e.g. Bol) insert rows here too. Processing happens
    in the worker."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('needs_mapping', 'Needs product mapping'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='inbox')
    topic = models.CharField(max_length=64)
    # Platform event id (e.g. X-Shopify-Webhook-Id) used for idempotency.
    external_event_id = models.CharField(max_length=255, blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default='')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Inbound event")
        verbose_name_plural = _("Inbound events")
        constraints = [
            models.UniqueConstraint(
                fields=['connection', 'external_event_id'],
                condition=~Q(external_event_id=''),
                name='unique_inbox_event_per_connection',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'received_at']),
        ]

    def __str__(self):
        return f"{self.topic} #{self.pk} ({self.status})"


class SyncOutbox(models.Model):
    """Outbound intents towards a platform, executed with retry/backoff by the
    worker so platform downtime never blocks pickers."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    ACTION_CHOICES = [
        ('fulfill_order', 'Fulfill order'),
        ('archive_order', 'Archive order'),
        ('push_inventory', 'Push inventory level'),
    ]

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='outbox')
    action = models.CharField(max_length=64, choices=ACTION_CHOICES)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='sync_outbox')
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=8)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Outbound task")
        verbose_name_plural = _("Outbound tasks")
        indexes = [
            models.Index(fields=['status', 'next_attempt_at']),
        ]

    def __str__(self):
        return f"{self.action} #{self.pk} ({self.status})"


class ProductLink(models.Model):
    """Mapping between an external product variant and an OrderPiqr Product.
    Resolved once (at product sync or first order), then order import is a
    cheap lookup. Manual overrides set locked=True and survive re-syncs."""

    MATCH_METHOD_CHOICES = [
        ('barcode', 'Barcode'),
        ('sku', 'SKU'),
        ('metafield', 'Metafield'),
        ('variant_id', 'Variant ID'),
        ('auto_created', 'Auto-created product'),
        ('manual', 'Manual'),
    ]

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='product_links')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='external_links',
                                null=True, blank=True)
    external_product_id = models.CharField(max_length=255, blank=True, default='')
    external_variant_id = models.CharField(max_length=255)
    # The identifier value that matched (or should match) Product.code.
    identifier_value = models.CharField(max_length=255, blank=True, default='')
    title = models.CharField(max_length=255, blank=True, default='')
    match_method = models.CharField(max_length=32, choices=MATCH_METHOD_CHOICES, blank=True, default='')
    locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Product link")
        verbose_name_plural = _("Product links")
        constraints = [
            models.UniqueConstraint(
                fields=['connection', 'external_variant_id'],
                name='unique_variant_per_connection',
            ),
        ]

    def __str__(self):
        target = self.product.code if self.product else 'UNRESOLVED'
        return f"{self.external_variant_id} -> {target}"


class ExternalOrderLink(models.Model):
    """Links an imported Order to its external counterpart."""

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='order_links')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='external_links')
    external_order_id = models.CharField(max_length=255)
    external_order_number = models.CharField(max_length=64, blank=True, default='')
    # Connector scratch space (e.g. Shopify fulfillment order ids).
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("External order link")
        verbose_name_plural = _("External order links")
        constraints = [
            models.UniqueConstraint(
                fields=['connection', 'external_order_id'],
                name='unique_external_order_per_connection',
            ),
        ]

    def __str__(self):
        return f"{self.external_order_number or self.external_order_id} -> {self.order.order_code}"

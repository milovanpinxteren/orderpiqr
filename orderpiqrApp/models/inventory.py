from django.utils.translation import gettext_lazy as _
from django.db import models
from django.contrib.auth.models import User

from .products import Product
from .devices import Device


class InventoryLog(models.Model):
    """
    Tracks all inventory quantity changes for audit purposes.
    """

    class ChangeType(models.TextChoices):
        SET = 'set', _('Set (absolute)')
        ADJUST = 'adjust', _('Adjust (relative)')

    class Reason(models.TextChoices):
        STOCK_COUNT = 'stock_count', _('Stock Count')
        RECEIVED = 'received', _('Goods Received')
        DAMAGED = 'damaged', _('Damaged')
        RETURNED = 'returned', _('Customer Return')
        CORRECTION = 'correction', _('Correction')
        ORDER_PICKED = 'order_picked', _('Order Picked')  # Phase 2
        OTHER = 'other', _('Other')

    log_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='inventory_logs',
        verbose_name=_("Product")
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("User")
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Device")
    )
    old_quantity = models.IntegerField(_("Old Quantity"))
    new_quantity = models.IntegerField(_("New Quantity"))
    change_type = models.CharField(
        _("Change Type"),
        max_length=10,
        choices=ChangeType.choices
    )
    reason = models.CharField(
        _("Reason"),
        max_length=20,
        choices=Reason.choices
    )
    notes = models.TextField(_("Notes"), blank=True, null=True)
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    # Phase 2 hook: reference to picklist that caused this change
    source_picklist = models.ForeignKey(
        'PickList',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Source Picklist"),
        help_text=_("If this change was caused by order completion, reference to the picklist.")
    )

    class Meta:
        verbose_name = _("Inventory Log")
        verbose_name_plural = _("Inventory Logs")
        ordering = ['-created_at']

    @property
    def quantity_change(self):
        """Returns the net change in quantity (positive or negative)."""
        return self.new_quantity - self.old_quantity

    def __str__(self):
        return _("Inventory change: %(product)s %(old)s -> %(new)s") % {
            "product": self.product.code,
            "old": self.old_quantity,
            "new": self.new_quantity
        }

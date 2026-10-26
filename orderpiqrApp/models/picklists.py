from django.utils.translation import gettext_lazy as _
from django.db import models
from .customers import Customer
from .orders import Order
from .devices import Device
from .products import Product


class PickList(models.Model):
    picklist_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Source Order"))
    picklist_code = models.CharField(_("Picklist Code"), max_length=255, null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name=_("Device"))
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    # auto_now (not auto_now_add): this was a duplicate of created_at that never
    # moved, so "when was this list last touched" was unanswerable — which is
    # what you need to tell a dead lock from a picker who is still working.
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    pick_started = models.BooleanField(_("Pick Started"), null=True, blank=True)
    pick_time = models.DateTimeField(_("Pick Time"), auto_now_add=True, null=True, blank=True)
    time_taken = models.DurationField(_("Time Taken"), null=True, blank=True)
    successful = models.BooleanField(_("Successful"), null=True, blank=True)
    # Archived hides a picklist from the health page without pretending it
    # completed. The row is never deleted — billing counts picklists.
    archived = models.BooleanField(_("Archived"), default=False)
    notes = models.TextField(_("Notes"), blank=True, null=True)

    class Meta:
        verbose_name = _("Pick List")
        verbose_name_plural = _("Pick Lists")
        unique_together = ['picklist_code', 'customer']


    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.device.lists_picked = self.device.picklist_set.count()
        self.device.save()

    def __str__(self):
        return _("PickList %(id)s for Device %(device)s") % {
            "id": self.picklist_id,
            "device": self.device.name
        }





class ProductPick(models.Model):
    class Outcome(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PICKED = 'picked', _('Picked')
        SHORT = 'short', _('Short')
        LOST = 'lost', _('Lost')

    class ShortReason(models.TextChoices):
        NOT_FOUND = 'not_found', _('Not found at location')
        INSUFFICIENT_STOCK = 'insufficient_stock', _('Insufficient stock')
        DAMAGED = 'damaged', _('Damaged')
        WRONG_PRODUCT = 'wrong_product', _('Wrong product')
        OTHER = 'other', _('Other')

    # `successful` is derived from `outcome` in save(); it stays a real column
    # because external API consumers still read and filter on it. The mapping's
    # load-bearing distinction: a declared short is False, but a lost row (the
    # server never heard anything) stays None — conflating them would erase
    # exactly the difference the outcome column exists to record.
    SUCCESSFUL_BY_OUTCOME = {
        Outcome.PENDING: None,
        Outcome.PICKED: True,
        Outcome.SHORT: False,
        Outcome.LOST: None,
    }

    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name=_("Product"))
    picklist = models.ForeignKey(PickList, related_name='products', on_delete=models.CASCADE,
                                 verbose_name=_("Pick List"))
    quantity = models.IntegerField(_("Quantity"))
    time_taken = models.DurationField(_("Time Taken"), null=True, blank=True)
    successful = models.BooleanField(_("Successful"), null=True, blank=True)
    outcome = models.CharField(_("Outcome"), max_length=16, choices=Outcome.choices,
                               default=Outcome.PENDING)
    short_reason = models.CharField(_("Short Reason"), max_length=32,
                                    choices=ShortReason.choices, blank=True, default='')
    notes = models.TextField(_("Notes"), blank=True, null=True)
    # The client's own id for the pick operation that marked this row. A phone
    # in a cold store loses reception mid-list and retries its queued picks, so
    # the same pick can arrive two or three times; this is what lets the server
    # recognise the replay and mark the row once. Not unique at the DB level:
    # one bulk operation stamps the same id on every row it marks.
    client_pick_id = models.CharField(_("Client Pick Id"), max_length=64, blank=True,
                                      default='', db_index=True)

    class Meta:
        verbose_name = _("Product Pick")
        verbose_name_plural = _("Product Picks")
        indexes = [
            models.Index(fields=['picklist', 'outcome']),
        ]

    def save(self, *args, **kwargs):
        # outcome is the source of truth; successful is always derived from it,
        # so an out-of-date writer that only sets successful cannot desync the
        # two columns.
        self.successful = self.SUCCESSFUL_BY_OUTCOME.get(self.outcome)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'outcome' in update_fields \
                and 'successful' not in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['successful']
        super().save(*args, **kwargs)

    @classmethod
    def outcome_from_successful(cls, successful):
        """Map a legacy `successful` write onto the outcome vocabulary."""
        if successful is True:
            return cls.Outcome.PICKED
        if successful is False:
            return cls.Outcome.SHORT
        return cls.Outcome.PENDING

    def __str__(self):
        return _("Pick of %(product)s in PickList %(picklist_id)s") % {
            "product": self.product,
            "picklist_id": self.picklist.picklist_id
        }


def resolve_pending_picks_to_lost(picklist):
    """Mark every still-pending row on a completed picklist as lost.

    A pending line on a list the picker finished is a pick the server never
    heard about. Queryset update on purpose: it skips save(), and lost rows
    keep successful=NULL — which is already the derived value for lost.
    """
    return ProductPick.objects.filter(
        picklist=picklist, outcome=ProductPick.Outcome.PENDING
    ).update(outcome=ProductPick.Outcome.LOST)


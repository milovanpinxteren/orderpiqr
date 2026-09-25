from django.utils.translation import gettext_lazy as _
from django.db import models

from .customers import Customer
from .devices import Device


class ScanEvent(models.Model):
    """A pick-flow health event: a scan that failed, a list that was rejected,
    or a manual override. Written best-effort from the scan endpoints and the
    picker client — logging must never block or break picking itself.
    """

    EVENT_TYPES = [
        ('unknown_product', _('Unknown product')),
        ('wrong_product', _('Wrong product scanned')),
        ('picklist_parse_error', _('Picklist could not be read')),
        ('picklist_rejected', _('Picklist rejected')),
        ('sync_error', _('Sync error')),
        ('manual_override', _('Manual override')),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name=_("Device"))
    event_type = models.CharField(_("Event Type"), max_length=32, choices=EVENT_TYPES)
    scanned_code = models.CharField(_("Scanned Code"), max_length=255, blank=True, default='')
    picklist_code = models.CharField(_("Picklist Code"), max_length=255, blank=True, default='')
    message = models.TextField(_("Message"), blank=True, default='')
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        verbose_name = _("Scan Event")
        verbose_name_plural = _("Scan Events")
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['customer', 'event_type', 'created_at']),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} ({self.scanned_code or self.picklist_code})"

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
        ('lock_takeover', _('Stale lock taken over')),
        # The silences: things that produced no event at all until now, which is
        # why a dashboard built only on scan outcomes looked clean while pickers
        # reported the app crashing and logging them out.
        ('client_error', _('App error')),
        ('app_lifecycle', _('App restarted or reloaded')),
        ('camera_error', _('Camera unavailable')),
        ('auth_bounce', _('Picker sent back to login')),
        # A picker declaring units they could not pick — recorded work, not a
        # failure of the app, hence severity info.
        ('short_pick', _('Short pick declared')),
    ]

    # event_type says what happened; severity says how much it hurt. Keeping
    # them apart is what lets the health page lead with blocking problems
    # instead of burying them under routine unknown-barcode noise.
    SEVERITIES = [
        ('info', _('Info')),
        ('warning', _('Warning')),
        ('error', _('Error')),
    ]

    # Default severity per type, used when a call site doesn't say otherwise.
    DEFAULT_SEVERITY = {
        'unknown_product': 'warning',
        'wrong_product': 'warning',
        'picklist_parse_error': 'warning',
        'picklist_rejected': 'error',
        'sync_error': 'error',
        'manual_override': 'info',
        'lock_takeover': 'warning',
        'client_error': 'error',
        'app_lifecycle': 'info',
        'camera_error': 'error',
        'auth_bounce': 'error',
        'short_pick': 'info',
    }

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name=_("Device"))
    event_type = models.CharField(_("Event Type"), max_length=32, choices=EVENT_TYPES)
    severity = models.CharField(_("Severity"), max_length=16, choices=SEVERITIES,
                                default='warning', db_index=True)
    # A slug distinguishing cases that share an event_type — three different
    # things were all logged as 'unknown_product', with the real difference
    # readable only in free-text `message`, which no aggregation can group by.
    reason = models.CharField(_("Reason"), max_length=64, blank=True, default='')
    scanned_code = models.CharField(_("Scanned Code"), max_length=255, blank=True, default='')
    picklist_code = models.CharField(_("Picklist Code"), max_length=255, blank=True, default='')
    message = models.TextField(_("Message"), blank=True, default='')
    # Which client build produced this. The v123 regression ran unnoticed for
    # three days because no event could be attributed to a release.
    build_id = models.CharField(_("Build"), max_length=64, blank=True, default='')
    # The device's own clock. Events queued while offline keep their real time
    # instead of collapsing onto the moment the network came back.
    client_ts = models.DateTimeField(_("Client Timestamp"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        verbose_name = _("Scan Event")
        verbose_name_plural = _("Scan Events")
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['customer', 'event_type', 'created_at']),
            models.Index(fields=['customer', 'severity', 'created_at']),
            models.Index(fields=['customer', 'device', 'created_at']),
            # The API's picklist_code filter (one list's events, nightly pulls)
            # had no index to lean on — the other four all key off event_type,
            # severity or device instead.
            models.Index(fields=['customer', 'picklist_code', 'created_at']),
        ]

    @property
    def occurred_at(self):
        """When this actually happened on the device, falling back to receipt."""
        return self.client_ts or self.created_at

    def __str__(self):
        return f"{self.get_event_type_display()} ({self.scanned_code or self.picklist_code})"

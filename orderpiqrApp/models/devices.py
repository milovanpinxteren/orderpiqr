from django.utils.translation import gettext_lazy as _
from django.db import models
from django.contrib.auth.models import User

from .customers import Customer


class Device(models.Model):
    """A physical device (browser) a picker works from.

    The fingerprint identifies the hardware, not the tenant: the same phone or
    shared tablet may legitimately be registered for several customers. So the
    fingerprint is unique *per customer*, not globally, and every lookup must be
    scoped by customer — see ``orderpiqrApp.utils.devices.resolve_device``.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name=_("User"))
    device_id = models.AutoField(primary_key=True)
    device_fingerprint = models.CharField(_("Device Fingerprint"), max_length=255, null=True, blank=True)
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    last_login = models.DateTimeField(_("Last Login"))
    lists_picked = models.IntegerField(_("Lists Picked"))

    class Meta:
        verbose_name = _("Device")
        verbose_name_plural = _("Devices")
        constraints = [
            models.UniqueConstraint(
                fields=['device_fingerprint', 'customer'],
                name='unique_device_fingerprint_per_customer',
            ),
        ]

    def __str__(self):
        return self.name



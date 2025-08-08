from django.utils.translation import gettext_lazy as _
from django.db import models
from django.contrib.auth.models import User

from .customers import Customer


class Device(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name=_("User"))
    device_id = models.AutoField(primary_key=True)
    device_fingerprint = models.CharField(_("Device Fingerprint"), max_length=255, unique=True, null=True, blank=True)
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    last_login = models.DateTimeField(_("Last Login"))
    lists_picked = models.IntegerField(_("Lists Picked"))

    class Meta:
        verbose_name = _("Device")
        verbose_name_plural = _("Devices")

    def __str__(self):
        return self.name



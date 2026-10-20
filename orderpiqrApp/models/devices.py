from django.utils.translation import gettext_lazy as _, pgettext_lazy
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
    # Translators: the label a warehouse gives a phone or tablet, e.g.
    # "Scanner 3" or "Tablet packing bench". Not a person's name.
    name = models.CharField(pgettext_lazy("device", "Name"), max_length=255)
    description = models.TextField(_("Description"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    # Despite the name this is last *activity*: stamped on every pick, not only
    # at login. It is what tells a live picker from an abandoned lock.
    last_login = models.DateTimeField(_("Last Login"))
    lists_picked = models.IntegerField(_("Lists Picked"))

    # What this device actually is. Parsed from the user agent, which
    # django_user_agents has been putting on every request all along without
    # anything reading it — so "is it one old phone or all of them?" was
    # unanswerable. Diagnostic only; the raw UA string is deliberately not kept.
    browser = models.CharField(_("Browser"), max_length=64, blank=True, default='')
    browser_version = models.CharField(_("Browser Version"), max_length=32, blank=True, default='')
    os = models.CharField(_("Operating System"), max_length=64, blank=True, default='')
    os_version = models.CharField(_("OS Version"), max_length=32, blank=True, default='')
    device_family = models.CharField(_("Device"), max_length=64, blank=True, default='')

    # 'standalone' = installed PWA, 'browser' = a plain tab. A browser tab is
    # subject to storage eviction that wipes the device identity, so this is the
    # field that separates "old phone" from "never installed the app".
    DISPLAY_MODES = [
        ('standalone', _('Installed app')),
        ('browser', _('Browser tab')),
    ]
    display_mode = models.CharField(_("Display Mode"), max_length=16, blank=True, default='',
                                    choices=DISPLAY_MODES)
    last_build_id = models.CharField(_("Last Build"), max_length=64, blank=True, default='')

    # Dead phones accumulate and there is no safe way to delete most of them:
    # PickList.device cascades, and billing counts picklists. Archiving hides a
    # device from the admin list without touching its history. It is not a
    # block: a device that shows activity again un-archives itself, see
    # ``orderpiqrApp.utils.devices.touch_device``.
    archived = models.BooleanField(_("Archived"), default=False)

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



import hashlib
import secrets

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from orderpiqrApp.utils.start_page import TOKEN_START_PAGE_CHOICES

from .customers import Customer

DEFAULT_VALIDITY_DAYS = 90


class PickerLoginToken(models.Model):
    """A scannable, revocable login credential for one orderpicker account.

    The raw token lives only in the QR code we render at issue time; the
    database keeps its sha256 (the same trade-off as
    ``drf_hashed_token.HashedToken``). A lost sheet is therefore replaced by
    issuing a new token, not by re-printing the old one.

    A QR is a bearer credential — whoever photographs it can start a picker
    session — so it is only ever issued for the low-privilege ``orderpicker``
    group, and ``customer`` pins it to one tenant so a token cannot follow a
    user account that is later moved to another company.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='picker_login_tokens',
        verbose_name=_("Picker"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    key_hash = models.CharField(_("Token Hash"), max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name=_("Created By"))
    created = models.DateTimeField(_("Created"), auto_now_add=True)
    expires_at = models.DateTimeField(_("Expires At"))
    revoked_at = models.DateTimeField(_("Revoked At"), null=True, blank=True)
    last_used_at = models.DateTimeField(_("Last Used At"), null=True, blank=True)
    use_count = models.PositiveIntegerField(_("Times Used"), default=0)
    # Lives here rather than in the QR image, so the landing page of a printed
    # sheet can be corrected without reprinting and redistributing it.
    start_page = models.CharField(
        _("Start Page"), max_length=16, blank=True, default='',
        choices=TOKEN_START_PAGE_CHOICES,
        help_text=_("Page this picker lands on after scanning. Blank follows the company setting."))

    class Meta:
        verbose_name = _("Picker Login QR")
        verbose_name_plural = _("Picker Login QRs")
        ordering = ['-created']

    def __str__(self):
        return f"Login QR for {self.user}"

    @staticmethod
    def hash_token(raw_token):
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @classmethod
    def generate_token(cls):
        raw_token = secrets.token_urlsafe(32)
        return raw_token, cls.hash_token(raw_token)

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def is_usable(self):
        return self.revoked_at is None and not self.is_expired

    @property
    def days_remaining(self):
        """Rounded up, so a freshly issued 90-day QR reads "90 days", not 89."""
        seconds = (self.expires_at - timezone.now()).total_seconds()
        return max(0, -(-int(seconds) // 86400))

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])

    def mark_used(self):
        PickerLoginToken.objects.filter(pk=self.pk).update(
            last_used_at=timezone.now(), use_count=models.F('use_count') + 1)

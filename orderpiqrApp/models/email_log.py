from django.db import models
from django.utils.translation import gettext_lazy as _


class EmailLog(models.Model):
    STATUS_CHOICES = [
        ('sent', _('Sent')),
        ('failed', _('Failed')),
    ]

    subject = models.CharField(max_length=500)
    from_email = models.EmailField()
    to_emails = models.TextField(help_text=_("Comma-separated recipients"))
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sent')
    error_message = models.TextField(blank=True)
    email_type = models.CharField(max_length=100, blank=True, help_text=_("e.g. password_reset, welcome"))
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Email Log")
        verbose_name_plural = _("Email Logs")

    def __str__(self):
        return f"[{self.status}] {self.subject} → {self.to_emails}"

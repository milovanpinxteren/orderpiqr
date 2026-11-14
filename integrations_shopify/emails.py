"""The one email a self-install merchant cannot do without.

Installing from the Shopify App Store creates an OrderPiqr workspace with a
companyadmin and an orderpicker account, both with random passwords nobody
ever sees. The embedded console could set the picker's password, so warehouse
staff could be let in — but the admin account was unreachable: no password, and
no email address to reset it to. Everything outside the console (products,
picker QR codes, scan health, settings) was therefore closed to every merchant
who installed from the App Store and never spoke to us.

This sends them a set-your-password link on activation, using the same token
machinery as the normal password-reset flow.
"""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


def set_password_url(user):
    """A one-shot link that lets `user` choose a password.

    Same generator as Django's password reset, so the link is invalidated by
    use, by a password change, or by expiry (PASSWORD_RESET_TIMEOUT).
    """
    path = reverse('password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    })
    return f"{settings.APP_BASE_URL}{path}"


def send_welcome_email(shop, force=False):
    """Mail the merchant their admin username and a set-password link.

    Called from `activate_shop`, which runs on every embedded-app load, so the
    send is guarded by `welcome_email_sent_at`. Returns True when a mail went
    out. Never raises: a failed SMTP connection must not break the console the
    merchant is currently looking at.
    """
    from integrations_shopify.services import admin_user_for

    if not shop.shop_email:
        return False
    if shop.welcome_email_sent_at and not force:
        return False
    if not shop.connection.auto_provisioned:
        # The shop was linked to an account the merchant already had. Telling
        # them to "set their admin password" for a workspace they have been
        # running for months — with a reset link for their own live account —
        # is wrong on both counts.
        return False

    customer = shop.connection.customer
    admin = admin_user_for(customer)
    if admin is None:
        return False

    context = {
        'shop_name': shop.shop_name or shop.shop_domain,
        'admin_username': admin.get_username(),
        'set_password_url': set_password_url(admin),
        'app_url': settings.APP_BASE_URL,
    }
    subject = _("Your OrderPiqr workspace for %(shop)s is ready") % {
        'shop': context['shop_name']}
    text_body = render_to_string('shopify/email/welcome.txt', context)

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[shop.shop_email],
        )
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Welcome email to %s failed for shop %s",
                         shop.shop_email, shop.shop_domain)
        return False

    shop.welcome_email_sent_at = timezone.now()
    shop.save(update_fields=['welcome_email_sent_at'])
    logger.info("Welcome email sent to %s for shop %s",
                shop.shop_email, shop.shop_domain)
    return True

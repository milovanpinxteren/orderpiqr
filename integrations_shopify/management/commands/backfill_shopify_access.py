"""Unstick the Shopify installs that were provisioned without a usable login.

Self-install created a companyadmin and an orderpicker account with random
passwords and no email address, so the merchant could neither log in to
orderpiqr.nl nor reset a password. The fix is in `activate_shop` now, but it
only runs when a merchant next opens the embedded console — and the merchants
this stranded are precisely the ones who stopped opening it.

    python manage.py backfill_shopify_access                  # report only
    python manage.py backfill_shopify_access --emails         # fill addresses
    python manage.py backfill_shopify_access --emails --welcome

--welcome sends real mail to real merchants. It is deliberately separate from
--emails, and skips any shop that already had its welcome mail.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from integrations_shopify import services
from integrations_shopify.emails import send_welcome_email
from integrations_shopify.models import ShopifyShop


class Command(BaseCommand):
    help = 'Backfill user emails (and optionally send welcome mail) for Shopify installs.'

    def add_arguments(self, parser):
        parser.add_argument('--emails', action='store_true',
                            help="Fill blank user emails from the shop's email.")
        parser.add_argument('--welcome', action='store_true',
                            help='Send the welcome email where it never went out.')
        parser.add_argument('--shop', default='',
                            help='Limit to one shop domain.')

    def handle(self, *args, **options):
        shops = (ShopifyShop.objects
                 .select_related('connection', 'connection__customer')
                 .order_by('installed_at'))
        if options['shop']:
            shops = shops.filter(shop_domain=options['shop'])

        for shop in shops:
            customer = shop.connection.customer
            users = list(User.objects.filter(userprofile__customer=customer))
            blank = [u for u in users if not u.email]
            never_logged_in = [u for u in users if u.last_login is None]

            self.stdout.write(
                f"\n{shop.shop_domain} -> customer {customer.pk} ({customer.name})")
            self.stdout.write(
                f"  status={shop.connection.status} auto_provisioned="
                f"{shop.connection.auto_provisioned} shop_email={shop.shop_email or '-'}")
            self.stdout.write(
                f"  users={len(users)} without_email={len(blank)} "
                f"never_logged_in={len(never_logged_in)} "
                f"welcome_sent={shop.welcome_email_sent_at or 'never'}")

            if options['emails']:
                filled = services.backfill_user_emails(shop)
                self.stdout.write(self.style.SUCCESS(
                    f"  filled {filled} address(es)")
                    if filled else "  no addresses to fill")

            if options['welcome']:
                if not shop.shop_email:
                    self.stdout.write("  no shop email on file — cannot write to them")
                elif shop.connection.status == 'disconnected':
                    self.stdout.write("  uninstalled — not mailing them")
                elif send_welcome_email(shop):
                    self.stdout.write(self.style.SUCCESS(
                        f"  welcome email sent to {shop.shop_email}"))
                else:
                    self.stdout.write("  welcome email not sent (already sent, or failed)")

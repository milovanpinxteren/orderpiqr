"""Where a picker lands after logging in.

Warehouses differ in how a picker starts work: some hand them a printed order
QR to scan, others have them claim the next job from the shared queue. That is
a property of the operation, not of the login method, so this module is the one
place that answers the question — ``root_redirect`` (password login, session
resume) and the QR login view both defer to it and therefore cannot drift.

Resolution order, most specific first:

1. the per-QR override on :class:`~orderpiqrApp.models.PickerLoginToken`
2. the customer's ``picker_start_page`` setting
3. :data:`AUTO` — the historical behaviour, derived from enabled features

Deliberately free of module-level model imports: ``PickerLoginToken`` imports
the choices from here, so anything heavier would be circular.
"""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

#: Follow the enabled features, as the app did before this setting existed.
AUTO = 'auto'
#: Straight to the scan screen, for warehouses that start an order by scanning.
SCAN = 'scan'
#: Straight to the shared order queue, for warehouses that claim the next job.
QUEUE = 'queue'

#: Offered per QR. The blank value means "whatever the company is set to", so a
#: printed code keeps following the company setting when that setting changes.
TOKEN_START_PAGE_CHOICES = [
    ('', _("Company default")),
    (SCAN, _("Scan an order")),
    (QUEUE, _("Order queue")),
]

#: Mirrors the above for the ``picker_start_page`` SettingDefinition. Stored in
#: the DB as plain strings by the migration, matching every other setting.
SETTING_KEY = 'picker_start_page'
SETTING_OPTIONS = [
    {'value': AUTO, 'label': 'Automatic'},
    {'value': SCAN, 'label': 'Scan an order'},
    {'value': QUEUE, 'label': 'Order queue'},
]


def _auto_url(customer):
    """The pre-setting behaviour: send them wherever their features point."""
    from orderpiqrApp.utils.inventory import is_inventory_enabled, is_orderpicking_enabled

    orderpicking = is_orderpicking_enabled(customer)
    inventory = is_inventory_enabled(customer)

    if orderpicking and inventory:
        return reverse('picker_choice')
    if orderpicking:
        return reverse('queue_picker')
    if inventory:
        return reverse('inventory_picker')
    return reverse('index')


def resolve_start_page(customer, override=''):
    """Absolute path a picker should land on after logging in.

    ``override`` is a token's ``start_page``; blank falls through to the
    customer setting. A choice whose feature is switched off is ignored rather
    than honoured — otherwise turning off order picking would strand every
    picker on a dead page, and a stale QR could outlive the feature it names.
    """
    from orderpiqrApp.utils.inventory import is_orderpicking_enabled

    choice = override or _customer_choice(customer)

    if choice in (SCAN, QUEUE) and not is_orderpicking_enabled(customer):
        choice = AUTO

    if choice == SCAN:
        return reverse('index')
    if choice == QUEUE:
        return reverse('queue_picker')
    return _auto_url(customer)


def _customer_choice(customer):
    """The customer's configured start page, or :data:`AUTO`.

    Falls back to the definition's ``default_value`` the same way
    ``get_customer_settings`` does, so changing the default in admin moves
    every customer who has not overridden it.
    """
    if not customer:
        return AUTO

    from orderpiqrApp.models import CustomerSettingValue, SettingDefinition

    value = (CustomerSettingValue.objects
             .filter(customer=customer, definition__key=SETTING_KEY)
             .values_list('value', flat=True)
             .first())
    if value is None:
        value = (SettingDefinition.objects
                 .filter(key=SETTING_KEY)
                 .values_list('default_value', flat=True)
                 .first())

    return value if value in (SCAN, QUEUE, AUTO) else AUTO

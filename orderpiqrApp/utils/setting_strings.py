"""Translations for the SettingDefinition rows, whose text lives in the database.

The settings page renders ``SettingDefinition.label`` / ``help_text`` and the
labels of its ``options`` straight out of the database, so gettext never saw
those strings: the page stayed English in every locale no matter how complete
the catalogs were.

The rows are seeded by data migrations. Those migrations must keep describing
the database as it was when they were written, and ``makemessages`` does not
read them anyway, so every seeded string is repeated here inside
``gettext_noop`` purely so that it lands in the catalog. Rendering then passes
the stored text back through :func:`translate_setting_text`.

When a migration adds or edits a SettingDefinition, add the new text here too.
``test_setting_strings.py`` compares this registry against what the migrations
actually seed and fails on drift. A string that is missing anyway is not a
crash — it simply renders in English.
"""

from django.utils.translation import gettext, gettext_noop

# Keyed by SettingDefinition.key. 'option_labels' lists the labels of the
# choice options in the order the migration seeds them.
SEEDED_SETTING_STRINGS = {
    'inventory_management_enabled': {
        'label': gettext_noop('Enable Inventory Management'),
        'help_text': gettext_noop(
            'When enabled, shows inventory quantities on products and allows inventory tracking.'
        ),
        'option_labels': [],
    },
    'orderpicking_enabled': {
        'label': gettext_noop('Enable Order Picking'),
        'help_text': gettext_noop(
            'When enabled, shows the order picking queue for pickers.'
        ),
        'option_labels': [],
    },
    'bulk_pick_enabled': {
        'label': gettext_noop('Enable Bulk Picking'),
        'help_text': gettext_noop(
            'When enabled, pickers can confirm multiple items of the same product at once instead of scanning each individually.'
        ),
        'option_labels': [],
    },
    'picker_start_page': {
        'label': gettext_noop('Picker start page'),
        'help_text': gettext_noop(
            "Where pickers land after logging in. Choose 'Scan an order' if pickers start work by scanning a printed order, or 'Order queue' if they pick the next job from the shared list. 'Automatic' keeps the previous behaviour."
        ),
        'option_labels': [
            gettext_noop('Automatic'),
            gettext_noop('Scan an order'),
            gettext_noop('Order queue'),
        ],
    },
    'grouped_picklist_view': {
        'label': gettext_noop('Grouped Picklist View'),
        'help_text': gettext_noop(
            'When enabled, the picker list shows one row per product with a quantity, instead of a separate row for each individual item. Pickers can still switch views themselves on the scan page.'
        ),
        'option_labels': [],
    },
    'bulk_pick_prominent_number': {
        'label': gettext_noop('Pick Popup: Prominent Number'),
        'help_text': gettext_noop(
            'Which number the pick confirmation popup emphasizes: the amount still to take (remaining) or the full line quantity (total). Warehouses that count out the whole quantity at the shelf should pick total. Pickers can still switch per session on the scan page.'
        ),
        'option_labels': [
            gettext_noop('Remaining to take'),
            gettext_noop('Total line quantity'),
        ],
    },
    'picklist_field_order': {
        'label': gettext_noop('Picklist QR Format'),
        'help_text': gettext_noop(
            'Column order of the rows inside your picklist QR codes. "Detect automatically" guesses using your product codes; set it explicitly if pickers see the "ambiguous picklist" error because a quantity also looks like a product code.'
        ),
        'option_labels': [
            gettext_noop('Detect automatically'),
            gettext_noop('Quantity, then product code'),
            gettext_noop('Product code, then quantity'),
        ],
    },
    'queue_enabled': {
        'label': gettext_noop('Order Queue'),
        'help_text': gettext_noop(
            'When enabled, pickers can claim orders from the shared queue. Disable for warehouses where pickers only scan printed picklist QRs: the queue pages are hidden and queue claims are blocked.'
        ),
        'option_labels': [],
    },
}


def translate_setting_text(text):
    """Look up database-stored setting text in the active locale's catalog.

    Returns ``text`` unchanged when it is empty or has no translation, so a
    setting whose wording was edited in the admin degrades to English instead
    of disappearing.
    """
    if not text:
        return text
    return gettext(str(text))


def translate_setting_options(options):
    """Translate the ``label`` of each ``{value, label}`` option.

    ``value`` is what gets stored and compared, so it is passed through
    untouched. Entries that are not shaped like options are returned as-is
    rather than raising, because ``options`` is a free-form JSONField.
    """
    if not options:
        return options
    translated = []
    for option in options:
        if not isinstance(option, dict):
            translated.append(option)
            continue
        entry = dict(option)
        if entry.get('label'):
            entry['label'] = translate_setting_text(entry['label'])
        translated.append(entry)
    return translated

"""The settings page must follow the active language.

``SettingDefinition.label`` / ``help_text`` / ``options`` are database text, so
makemessages cannot see them and the page rendered English in every locale.
``orderpiqrApp.utils.setting_strings`` repeats the seeded wording inside
``gettext_noop`` to get it into the catalog. That registry is hand-maintained,
so the drift test below is the thing that actually keeps it honest: it compares
the registry against the rows the migrations really seeded, which the test
database already contains.
"""
from django.test import TestCase
from django.utils.translation import activate, deactivate

from orderpiqrApp.models import SettingDefinition
from orderpiqrApp.utils.setting_strings import (
    SEEDED_SETTING_STRINGS, translate_setting_options, translate_setting_text)


class SeededSettingStringsTestCase(TestCase):
    """Every string the migrations seed is registered for translation."""

    def test_every_seeded_setting_is_registered(self):
        missing = sorted(
            SettingDefinition.objects.exclude(
                key__in=SEEDED_SETTING_STRINGS
            ).values_list('key', flat=True)
        )
        self.assertEqual(
            missing, [],
            'SettingDefinition rows with no entry in SEEDED_SETTING_STRINGS — '
            'their labels will render untranslated: %s' % missing)

    def test_registered_text_matches_the_database(self):
        for definition in SettingDefinition.objects.all():
            registered = SEEDED_SETTING_STRINGS.get(definition.key)
            if registered is None:
                continue  # reported by test_every_seeded_setting_is_registered
            with self.subTest(key=definition.key):
                self.assertEqual(
                    definition.label, registered['label'],
                    'label drifted from the registry, so it is no longer in the catalog')
                self.assertEqual(
                    definition.help_text, registered['help_text'],
                    'help_text drifted from the registry, so it is no longer in the catalog')
                self.assertEqual(
                    [option['label'] for option in (definition.options or [])],
                    registered['option_labels'],
                    'option labels drifted from the registry')

    def test_no_stale_registry_entries(self):
        stale = sorted(
            set(SEEDED_SETTING_STRINGS) - set(
                SettingDefinition.objects.values_list('key', flat=True))
        )
        self.assertEqual(
            stale, [],
            'SEEDED_SETTING_STRINGS entries for settings no migration seeds: %s' % stale)


class TranslateSettingTextTestCase(TestCase):
    """The render-time helpers stay safe on anything the admin can store."""

    def tearDown(self):
        deactivate()

    def test_known_label_is_translated(self):
        activate('nl')
        definition = SettingDefinition.objects.get(key='queue_enabled')
        self.assertNotEqual(
            definition.translated_label, definition.label,
            'the Dutch catalog has no translation for this setting label')

    def test_unknown_text_falls_back_to_itself(self):
        activate('nl')
        self.assertEqual(
            translate_setting_text('Wording typed straight into the admin'),
            'Wording typed straight into the admin')

    def test_empty_text_is_passed_through(self):
        for value in ('', None):
            with self.subTest(value=value):
                self.assertEqual(translate_setting_text(value), value)

    def test_option_values_are_never_translated(self):
        activate('nl')
        definition = SettingDefinition.objects.get(key='picker_start_page')
        self.assertEqual(
            [option['value'] for option in definition.translated_options],
            [option['value'] for option in definition.options],
            'option values are stored and compared — translating them breaks saving')

    def test_malformed_options_do_not_raise(self):
        activate('nl')
        self.assertEqual(
            translate_setting_options(['not a dict', {'value': 'x'}, {}]),
            ['not a dict', {'value': 'x'}, {}])

    def test_empty_options_are_passed_through(self):
        for value in ([], None):
            with self.subTest(value=value):
                self.assertEqual(translate_setting_options(value), value)

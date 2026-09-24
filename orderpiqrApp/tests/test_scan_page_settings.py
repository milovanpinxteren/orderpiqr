"""The scan-page customer settings that the picker UI reads from
window.SETTINGS: the data-migration-seeded definitions and their defaults."""
from django.test import TestCase

from orderpiqrApp.models import Customer, SettingDefinition
from orderpiqrApp.views.main_views import get_customer_settings


class ScanPageSettingDefinitionTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Healthy Fridge')

    def test_prominent_number_setting_defaults_to_remaining(self):
        definition = SettingDefinition.objects.get(key='bulk_pick_prominent_number')
        self.assertEqual(definition.default_value, 'remaining')
        values = [o['value'] for o in definition.options]
        self.assertEqual(values, ['remaining', 'total'])
        self.assertEqual(get_customer_settings(self.customer)['bulk_pick_prominent_number'],
                         'remaining')

    def test_picklist_field_order_setting_defaults_to_auto(self):
        definition = SettingDefinition.objects.get(key='picklist_field_order')
        self.assertEqual(definition.default_value, 'auto')
        values = [o['value'] for o in definition.options]
        self.assertEqual(values, ['auto', 'quantity_first', 'product_first'])
        self.assertEqual(get_customer_settings(self.customer)['picklist_field_order'], 'auto')

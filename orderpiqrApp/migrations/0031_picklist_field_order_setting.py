from django.db import migrations


def create_field_order_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='picklist_field_order',
        defaults={
            'label': 'Picklist QR Format',
            'help_text': 'Column order of the rows inside your picklist QR codes. '
                         '"Detect automatically" guesses using your product codes; set it '
                         'explicitly if pickers see the "ambiguous picklist" error because '
                         'a quantity also looks like a product code.',
            'setting_type': 'str',
            'default_value': 'auto',
            'options': [
                {"value": "auto", "label": "Detect automatically"},
                {"value": "quantity_first", "label": "Quantity, then product code"},
                {"value": "product_first", "label": "Product code, then quantity"},
            ],
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='picklist_field_order').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0030_bulk_pick_prominent_setting'),
    ]

    operations = [
        migrations.RunPython(create_field_order_setting, reverse_migration),
    ]

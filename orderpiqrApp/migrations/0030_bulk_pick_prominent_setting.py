from django.db import migrations


def create_prominent_number_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='bulk_pick_prominent_number',
        defaults={
            'label': 'Pick Popup: Prominent Number',
            'help_text': 'Which number the pick confirmation popup emphasizes: the amount still to take '
                         '(remaining) or the full line quantity (total). Warehouses that count out the '
                         'whole quantity at the shelf should pick total. '
                         'Pickers can still switch per session on the scan page.',
            'setting_type': 'str',
            'default_value': 'remaining',
            'options': [
                {"value": "remaining", "label": "Remaining to take"},
                {"value": "total", "label": "Total line quantity"},
            ],
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='bulk_pick_prominent_number').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0029_grouped_picklist_view'),
    ]

    operations = [
        migrations.RunPython(create_prominent_number_setting, reverse_migration),
    ]

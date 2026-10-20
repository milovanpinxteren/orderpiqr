from django.db import migrations


def create_picklist_search_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='picklist_search_enabled',
        defaults={
            'label': 'Picklist search',
            'help_text': 'Let pickers search for an order by its code and claim it '
                         'without scanning the QR code.',
            'setting_type': 'bool',
            'default_value': 'false',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='picklist_search_enabled').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0038_backfill_scan_event_severity'),
    ]

    operations = [
        migrations.RunPython(create_picklist_search_setting, reverse_migration),
    ]

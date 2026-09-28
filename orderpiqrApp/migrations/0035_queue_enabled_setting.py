from django.db import migrations


def create_queue_enabled_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='queue_enabled',
        defaults={
            'label': 'Order Queue',
            'help_text': 'When enabled, pickers can claim orders from the shared queue. '
                         'Disable for warehouses where pickers only scan printed picklist QRs: '
                         'the queue pages are hidden and queue claims are blocked.',
            'setting_type': 'bool',
            'default_value': 'true',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='queue_enabled').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0034_productbarcode'),
    ]

    operations = [
        migrations.RunPython(create_queue_enabled_setting, reverse_migration),
    ]

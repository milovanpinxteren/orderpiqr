from django.db import migrations


def create_orderpicking_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='orderpicking_enabled',
        defaults={
            'label': 'Enable Order Picking',
            'help_text': 'When enabled, shows the order picking queue for pickers.',
            'setting_type': 'bool',
            'default_value': 'true',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='orderpicking_enabled').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0021_add_inventory_soft_delete'),
    ]

    operations = [
        migrations.RunPython(create_orderpicking_setting, reverse_migration),
    ]

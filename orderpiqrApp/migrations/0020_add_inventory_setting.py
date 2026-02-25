from django.db import migrations


def create_inventory_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='inventory_management_enabled',
        defaults={
            'label': 'Enable Inventory Management',
            'help_text': 'When enabled, shows inventory quantities on products and allows inventory tracking.',
            'setting_type': 'bool',
            'default_value': 'false',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='inventory_management_enabled').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0019_add_inventory_management'),
    ]

    operations = [
        migrations.RunPython(create_inventory_setting, reverse_migration),
    ]

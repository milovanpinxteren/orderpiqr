from django.db import migrations


def create_bulk_pick_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='bulk_pick_enabled',
        defaults={
            'label': 'Enable Bulk Picking',
            'help_text': 'When enabled, pickers can confirm multiple items of the same product at once instead of scanning each individually.',
            'setting_type': 'bool',
            'default_value': 'false',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='bulk_pick_enabled').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0022_add_orderpicking_setting'),
    ]

    operations = [
        migrations.RunPython(create_bulk_pick_setting, reverse_migration),
    ]

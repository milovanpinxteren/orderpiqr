from django.db import migrations


def create_grouped_view_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='grouped_picklist_view',
        defaults={
            'label': 'Grouped Picklist View',
            'help_text': 'When enabled, the picker list shows one row per product with a quantity, '
                         'instead of a separate row for each individual item. '
                         'Pickers can still switch views themselves on the scan page.',
            'setting_type': 'bool',
            'default_value': 'false',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='grouped_picklist_view').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0028_picker_start_page'),
    ]

    operations = [
        migrations.RunPython(create_grouped_view_setting, reverse_migration),
    ]

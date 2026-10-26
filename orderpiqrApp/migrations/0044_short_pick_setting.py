from django.db import migrations


def create_short_pick_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key='short_pick_enabled',
        defaults={
            'label': 'Short picks',
            'help_text': 'Let pickers report items they cannot pick (missing, '
                         'damaged, wrong product) instead of leaving the line pending.',
            'setting_type': 'bool',
            'default_value': 'false',
        }
    )


def reverse_migration(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key='short_pick_enabled').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0043_backfill_productpick_outcome'),
    ]

    operations = [
        migrations.RunPython(create_short_pick_setting, reverse_migration),
    ]

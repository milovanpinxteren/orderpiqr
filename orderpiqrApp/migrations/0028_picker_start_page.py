from django.db import migrations, models

# Duplicated from orderpiqrApp.utils.start_page on purpose: a migration must
# keep describing the schema as it was when written, even if those constants
# are later renamed or removed.
SETTING_KEY = 'picker_start_page'
SETTING_OPTIONS = [
    {'value': 'auto', 'label': 'Automatic'},
    {'value': 'scan', 'label': 'Scan an order'},
    {'value': 'queue', 'label': 'Order queue'},
]


def create_start_page_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.get_or_create(
        key=SETTING_KEY,
        defaults={
            'label': 'Picker start page',
            'help_text': (
                "Where pickers land after logging in. Choose 'Scan an order' if pickers "
                "start work by scanning a printed order, or 'Order queue' if they pick the "
                "next job from the shared list. 'Automatic' keeps the previous behaviour."
            ),
            'setting_type': 'str',
            # 'auto' so existing customers see no change until they choose.
            'default_value': 'auto',
            'options': SETTING_OPTIONS,
        }
    )


def remove_start_page_setting(apps, schema_editor):
    SettingDefinition = apps.get_model('orderpiqrApp', 'SettingDefinition')
    SettingDefinition.objects.filter(key=SETTING_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0027_picker_login_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='pickerlogintoken',
            name='start_page',
            field=models.CharField(
                blank=True, default='', max_length=16,
                choices=[('', 'Company default'), ('scan', 'Scan an order'), ('queue', 'Order queue')],
                help_text='Page this picker lands on after scanning. Blank follows the company setting.',
                verbose_name='Start Page'),
        ),
        migrations.RunPython(create_start_page_setting, remove_start_page_setting),
    ]

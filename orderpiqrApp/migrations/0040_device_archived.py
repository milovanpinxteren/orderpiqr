from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0039_picklist_search_setting'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='archived',
            field=models.BooleanField(default=False, verbose_name='Archived'),
        ),
    ]

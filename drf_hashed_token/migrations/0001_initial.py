import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HashedToken',
            fields=[
                ('key_hash', models.CharField(editable=False, max_length=64, primary_key=True, serialize=False, verbose_name='Token Hash')),
                ('stage', models.CharField(choices=[('LIVE', 'Live'), ('TEST', 'Test')], default='TEST', max_length=4)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='drf_hashed_token', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'API Token',
                'verbose_name_plural': 'API Tokens',
                'unique_together': {('user', 'stage')},
            },
        ),
    ]

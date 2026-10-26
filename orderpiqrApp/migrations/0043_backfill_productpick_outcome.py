"""Translate the historical `successful` column into the outcome vocabulary.

0042 added `outcome` with a blanket default of 'pending', which would file
every recorded pick in history as still-waiting. Backfill from what the old
column can prove: True was a recorded pick; False was the one legacy failure
path (reason unknown, hence 'other'); NULL on a picklist that completed is a
pick the server never heard about — lost, not pending. NULL on an open list
genuinely is pending and keeps the default.

Literal queries rather than model imports (0038 precedent): a migration must
keep describing the past even after the model's mapping changes.
"""
from django.db import migrations


def set_outcome(apps, schema_editor):
    ProductPick = apps.get_model('orderpiqrApp', 'ProductPick')
    ProductPick.objects.filter(successful=True).update(outcome='picked')
    ProductPick.objects.filter(successful=False).update(
        outcome='short', short_reason='other')
    ProductPick.objects.filter(
        successful__isnull=True, picklist__successful=True).update(outcome='lost')


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0042_productpick_outcome'),
    ]

    operations = [
        migrations.RunPython(set_outcome, migrations.RunPython.noop),
    ]

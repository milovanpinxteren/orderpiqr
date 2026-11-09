from django.db import migrations, models


class Migration(migrations.Migration):
    """Record per row whether a pick was verified by a scan.

    Nullable with no backfill on purpose: existing rows genuinely do not say
    how they were confirmed. The override history lives in ScanEvent, but one
    bulk confirm is a single event covering many rows, so there is no honest
    way to distribute those events back over the lines they marked — guessing
    would fabricate exactly the number this column exists to measure.
    """

    dependencies = [
        ('orderpiqrApp', '0045_scanevent_picklist_code_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='productpick',
            name='scan_verified',
            field=models.BooleanField(blank=True, null=True, verbose_name='Scan Verified'),
        ),
    ]

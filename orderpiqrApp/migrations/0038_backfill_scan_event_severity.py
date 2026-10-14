"""Give historical events the severity their type implies.

0037 added `severity` with a blanket default of 'warning', which would file
every past manual override as a warning and every past sync error and rejected
picklist as one too — flattening exactly the distinction the health page is
being rebuilt around. Backfill from the model's own mapping so history and new
events read the same way.
"""
from django.db import migrations

# Spelled out rather than imported from the model: a migration must keep
# describing the past even after the model's mapping changes.
SEVERITY_BY_TYPE = {
    'unknown_product': 'warning',
    'wrong_product': 'warning',
    'picklist_parse_error': 'warning',
    'picklist_rejected': 'error',
    'sync_error': 'error',
    'manual_override': 'info',
    'lock_takeover': 'warning',
    'client_error': 'error',
    'app_lifecycle': 'info',
    'camera_error': 'error',
    'auth_bounce': 'error',
}


def set_severity(apps, schema_editor):
    ScanEvent = apps.get_model('orderpiqrApp', 'ScanEvent')
    for event_type, severity in SEVERITY_BY_TYPE.items():
        if severity == 'warning':
            continue  # already the column default
        ScanEvent.objects.filter(event_type=event_type).update(severity=severity)


def reset_severity(apps, schema_editor):
    ScanEvent = apps.get_model('orderpiqrApp', 'ScanEvent')
    ScanEvent.objects.all().update(severity='warning')


class Migration(migrations.Migration):

    dependencies = [
        ('orderpiqrApp', '0037_device_browser_device_browser_version_and_more'),
    ]

    operations = [
        migrations.RunPython(set_severity, reset_severity),
    ]

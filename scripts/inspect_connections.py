"""One-off debug helper: print integration connections.
Run: heroku run -- python scripts/inspect_connections.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'orderpiqr.settings')

import django  # noqa: E402

django.setup()

from integrations.models import Connection  # noqa: E402

for c in Connection.objects.all():
    print(c.pk, c.platform, c.customer.name, c.status,
          'auto_provisioned=', c.auto_provisioned)

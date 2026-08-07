"""One-off debug helper: print integration connections (heroku run)."""
from integrations.models import Connection

for c in Connection.objects.all():
    print(c.pk, c.platform, c.customer.name, c.status, 'auto_provisioned=', c.auto_provisioned)

"""Dev entry point used by `shopify app dev` (see shopify.app.toml).

The CLI provides PORT plus SHOPIFY_API_KEY/SHOPIFY_API_SECRET in the
environment and tunnels the public app URL to this process. Runs the Django
dev server and the integrations worker side by side."""

import os
import subprocess
import sys

port = os.environ.get('PORT') or os.environ.get('FRONTEND_PORT') or '8000'

worker = subprocess.Popen([sys.executable, 'manage.py', 'run_integrations_worker'])
try:
    # The CLI proxy connects to ::1 (IPv6 loopback) on Windows
    subprocess.run([sys.executable, 'manage.py', 'runserver', f'[::1]:{port}'], check=False)
finally:
    worker.terminate()

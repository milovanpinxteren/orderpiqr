import json
import logging

from api.models import APIRequestLog

logger = logging.getLogger(__name__)

# Paths whose non-2xx responses are worth keeping. `/api/` is logged in full
# (it is the integration surface and volume is low); the picker flow is logged
# only when something went wrong.
#
# Why the picker flow is here at all: it used to be logged nowhere. Django's
# LOGGING is console-only, so a 500 on a pick endpoint existed solely in
# Heroku's rolling log buffer and was unrecoverable by the time a warehouse
# manager phoned the next morning. "There were a lot of errors" could not be
# checked against anything.
ERROR_ONLY_PREFIXES = ('/orderpiqr/', '/q/')

# Bot noise. The log is for diagnosing our own app, and vulnerability scanners
# probing /api/.env would otherwise be the overwhelming majority of rows.
SCANNER_SUFFIXES = ('.env', '.git', '.bak', '.sql', '.yml', '.yaml', '.ini',
                    '.tfstate', 'wp-config.php', 'wp-login.php', '.aws/credentials')


class APILoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        try:
            if self._should_log(request, response):
                APIRequestLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    method=request.method,
                    path=request.path[:255],
                    status_code=response.status_code,
                )
        except Exception:
            # Request logging must never turn a working response into a 500.
            logger.warning('Request logging failed for %s', request.path, exc_info=True)

        return response

    def _should_log(self, request, response):
        path = request.path

        if any(path.endswith(suffix) for suffix in SCANNER_SUFFIXES):
            return False

        if path.startswith('/api/'):
            return True

        if path.startswith(ERROR_ONLY_PREFIXES):
            # 404s on the pick endpoints are meaningful, not noise: a
            # picklist_not_found is a picker whose list vanished mid-shift.
            return response.status_code >= 400

        return False

"""Branded error views that Django cannot route through handler4xx.

The handler400/403/404/500 views live in ``orderpiqr.views``. CSRF failures are
different: ``CsrfViewMiddleware`` never raises ``PermissionDenied``, it calls
``settings.CSRF_FAILURE_VIEW`` directly, so handler403 is bypassed and the user
gets Django's unbranded debug-ish page. This module supplies the branded one.
"""

import logging

from django.shortcuts import render

logger = logging.getLogger(__name__)

CSRF_FAILURE_TEMPLATE_NAME = "403_csrf.html"


def csrf_failure(request, reason="", template_name=CSRF_FAILURE_TEMPLATE_NAME):
    """Render the branded "your session expired" page for a CSRF rejection.

    Signature matches ``django.views.csrf.csrf_failure`` so the
    ``check_csrf_failure_view`` system check passes.

    The template name is Django's own default, so even if CSRF_FAILURE_VIEW is
    ever unset the built-in view still finds the branded template.
    """
    logger.warning(
        "CSRF failure (403) at %s: %s | Method: %s | User: %s | Referer: %s",
        request.path,
        reason,
        request.method,
        getattr(request, "user", "Anonymous"),
        request.META.get("HTTP_REFERER", ""),
    )
    return render(request, template_name, status=403)

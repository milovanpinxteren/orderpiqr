from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils.translation import gettext as _

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse

from orderpiqrApp.models import UserProfile
from orderpiqrApp.utils.health import health_window, pick_outcomes


@extend_schema(
    tags=["health"],
    summary="Pick-flow health counters",
    description="""
    The same counters shown on the manage health page's outcome tiles, as a
    tenant-scoped aggregate: how many lists and lines were picked, declared
    short, or lost (recorded as pending on a list the device marked complete,
    and never heard from again), plus fleet facts for the same window
    (restarted lists, devices seen, devices still on an old build).

    **Window:** defaults to a rolling 24 hours, like the HTML page. For a
    reproducible nightly pull, always pass explicit `date_from`/`date_to`
    rather than relying on the rolling default — "last 24 hours" means a
    different window every time it's called.
    """,
    parameters=[
        OpenApiParameter(
            name='date_from', type=str, required=False,
            description='Start date (YYYY-MM-DD), inclusive from midnight. '
                        'Takes precedence over `preset` when given.'),
        OpenApiParameter(
            name='date_to', type=str, required=False,
            description='End date (YYYY-MM-DD), inclusive through 23:59:59.59. '
                        'Takes precedence over `preset` when given.'),
        OpenApiParameter(
            name='preset', type=str, required=False,
            description="One of `24h` (default), `today`, `yesterday`, `7d`, `30d`. "
                        "Ignored once `date_from` or `date_to` is given."),
    ],
    responses={
        200: OpenApiResponse(
            description="Pick-flow health counters for the window",
            examples=[
                OpenApiExample(
                    name="Health Outcomes Response",
                    value={
                        "window": {
                            "start": "2026-10-25T09:00:00Z",
                            "end": "2026-10-26T09:00:00Z",
                            "preset": "24h",
                        },
                        "current_build": "a1b2c3d4",
                        "outcomes": {
                            "lists_total": 42,
                            "lists_completed": 38,
                            "lists_open": 4,
                            "lines_total": 610,
                            "lines_short": 12,
                            "lines_lost": 3,
                            "lines_lost_pct": 0.5,
                            "lists_restarted": 2,
                            "devices_used": 6,
                            "devices_on_old_build": 1,
                        },
                    }
                )
            ]
        ),
        401: OpenApiResponse(description="Not authenticated"),
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def health_outcomes(request):
    """Pick-flow health counters for the requesting user's customer."""
    try:
        customer = request.user.userprofile.customer
    except UserProfile.DoesNotExist:
        return Response({'detail': _('No customer profile found')}, status=status.HTTP_400_BAD_REQUEST)

    start, end, preset, _label = health_window(request.query_params)
    outcomes, current_build = pick_outcomes(customer, start, end)

    return Response({
        'window': {
            'start': start,
            'end': end,
            'preset': preset,
        },
        'current_build': current_build,
        'outcomes': outcomes,
    })

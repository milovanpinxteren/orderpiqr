from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated

from drf_spectacular.utils import extend_schema, extend_schema_view

from api.serializers import ScanEventSerializer
from orderpiqrApp.models import ScanEvent


@extend_schema_view(
    list=extend_schema(
        summary="List scan events",
        description="""
        Retrieve pick-flow health events for the authenticated user's customer:
        failed scans, rejected picklists, manual overrides, and the "silent"
        client-side events (app errors, camera failures, forced logouts) that
        nothing else on the scan page surfaces.

        **Search:** Use the `?search=` query parameter to match `scanned_code`,
        `picklist_code`, `reason` or `message`.

        **Filtering:**
        - `?created_at__gte=2026-10-01T00:00:00Z` - Events received on or after this time
        - `?created_at__lte=2026-10-02T00:00:00Z` - Events received on or before this time
        - `?event_type=wrong_product` - Filter by event type (see the ScanEvent model
          for the full list: `unknown_product`, `wrong_product`, `picklist_rejected`,
          `sync_error`, `manual_override`, `lock_takeover`, `client_error`,
          `app_lifecycle`, `camera_error`, `auth_bounce`, `short_pick`)
        - `?severity=error` - Filter by severity (`info`, `warning`, `error`)
        - `?picklist_code=ORDER-2026-001` - Filter by the picklist the event happened on
        - `?device=12` - Filter by device ID

        **Ordering:** Defaults to newest first (`created_at`). Also sortable by
        `?ordering=client_ts`, `?ordering=severity`, `?ordering=event_type`.

        **Nightly pulls:** always pass an explicit `created_at__gte`/`created_at__lte`
        window rather than paging the whole table — the same `?picklist_code=` and
        `?created_at__` combination HF's own health page uses is indexed for it.
        This endpoint is read-only: events are written by the scan flow itself,
        never through the API.
        """
    ),
    retrieve=extend_schema(
        summary="Get scan event details",
        description="Retrieve a single scan event by id."
    ),
)
@extend_schema(tags=["scanevents"])
class ScanEventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing pick-flow health events.

    Read-only: writes happen exclusively from the scan endpoints and the
    picker client's own best-effort logging, never through this API.
    """
    queryset = ScanEvent.objects.none()  # Required for drf-spectacular
    serializer_class = ScanEventSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['scanned_code', 'picklist_code', 'reason', 'message']
    # ScanEvent has no Meta.ordering, so OrderingFilter needs an explicit
    # default or an unordered queryset leaks through on every request.
    ordering_fields = ['created_at', 'client_ts', 'severity', 'event_type']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = ScanEvent.objects.filter(
            customer=self.request.user.userprofile.customer
        ).select_related('device')

        # Manual filtering by query params, per house convention.
        created_after = self.request.query_params.get('created_at__gte')
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)

        created_before = self.request.query_params.get('created_at__lte')
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)

        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)

        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)

        picklist_code = self.request.query_params.get('picklist_code')
        if picklist_code:
            queryset = queryset.filter(picklist_code=picklist_code)

        device_id = self.request.query_params.get('device')
        if device_id:
            queryset = queryset.filter(device_id=device_id)

        return queryset

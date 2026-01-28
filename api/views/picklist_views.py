from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import PickListSerializer, PickListDetailSerializer
from orderpiqrApp.models import PickList
from rest_framework import filters
from django.db.models import Avg, Count, Q
from django.utils import timezone
from datetime import timedelta

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiResponse


@extend_schema_view(
    list=extend_schema(
        summary="List all pick lists",
        description="""
        Retrieve a list of all pick lists for the authenticated user's customer.

        **Search:** Use the `?search=` query parameter to filter by picklist_code or notes.

        **Filtering:**
        - `?successful=true` - Only successful pick lists
        - `?successful=false` - Only failed pick lists
        - `?pick_started=true` - Only started pick lists
        - `?device=1` - Filter by device ID
        - `?order=42` - Filter by order ID

        **Ordering:**
        - `?ordering=-created_at` - Sort by creation date (newest first)
        - `?ordering=picklist_code` - Sort by code

        A PickList represents a picking job assigned to a device/worker.
        """
    ),
    retrieve=extend_schema(
        summary="Get pick list details",
        description="Retrieve details of a specific pick list, including all product picks and order information."
    ),
    create=extend_schema(
        summary="Create a pick list",
        description="""
        Create a new pick list manually.

        **Note:** Pick lists are typically created automatically when an order is claimed
        from the queue via `POST /api/queue/claim/{order_id}/`. Use this endpoint only
        for manual/ad-hoc picking operations.
        """
    ),
    update=extend_schema(
        summary="Update a pick list",
        description="Update pick list details, including completion status and notes."
    ),
    partial_update=extend_schema(
        summary="Partially update a pick list",
        description="Update specific fields of a pick list."
    ),
    destroy=extend_schema(
        summary="Delete a pick list",
        description="**Not allowed.** Pick lists cannot be deleted to maintain audit trails."
    ),
)
@extend_schema(
    tags=["picklists"],
    examples=[
        OpenApiExample(
            name="PickList Example",
            description="A pick list representing a picking operation",
            value={
                "picklist_code": "ORDER-2025-001",
                "device": 1,
                "order": 42,
                "pick_started": True,
                "successful": None,
                "notes": ""
            },
            request_only=True
        )
    ]
)
class PickListViewSet(viewsets.ModelViewSet):
    queryset = PickList.objects.none()  # Required for drf-spectacular
    serializer_class = PickListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['picklist_code', 'notes']
    ordering_fields = ['created_at', 'updated_at', 'picklist_code', 'successful']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = PickList.objects.filter(
            customer=self.request.user.userprofile.customer
        ).select_related('device', 'order')

        # Manual filtering
        successful = self.request.query_params.get('successful')
        if successful is not None:
            if successful.lower() == 'true':
                queryset = queryset.filter(successful=True)
            elif successful.lower() == 'false':
                queryset = queryset.filter(successful=False)

        pick_started = self.request.query_params.get('pick_started')
        if pick_started is not None:
            queryset = queryset.filter(pick_started=pick_started.lower() == 'true')

        device_id = self.request.query_params.get('device')
        if device_id:
            queryset = queryset.filter(device_id=device_id)

        order_id = self.request.query_params.get('order')
        if order_id:
            queryset = queryset.filter(order_id=order_id)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PickListDetailSerializer
        return PickListSerializer

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user.userprofile.customer)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(
        summary="Complete a pick list",
        description="""
        Mark a pick list as complete. This will also update the associated order status to 'completed'.

        **Request body (optional):**
        - `successful`: Boolean indicating if all picks were successful
        - `notes`: Any notes about the picking operation
        """,
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "successful": {"type": "boolean", "default": True},
                    "notes": {"type": "string"}
                }
            }
        },
        responses={
            200: OpenApiResponse(
                description="Pick list completed",
                examples=[
                    OpenApiExample(
                        name="Success Response",
                        value={
                            "status": "ok",
                            "message": "Pick list completed",
                            "picklist_id": 1,
                            "order_status": "completed",
                            "time_taken": "00:05:30"
                        }
                    )
                ]
            )
        }
    )
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Complete a pick list and its associated order."""
        picklist = self.get_object()

        successful = request.data.get('successful', True)
        notes = request.data.get('notes', '')

        # Calculate time taken
        if picklist.pick_time:
            picklist.time_taken = timezone.now() - picklist.pick_time

        picklist.successful = successful
        if notes:
            picklist.notes = notes
        picklist.save()

        # Update order status if linked
        order_status = None
        if picklist.order:
            picklist.order.status = 'completed'
            picklist.order.completed_at = timezone.now()
            picklist.order.save(update_fields=['status', 'completed_at'])
            order_status = 'completed'

        return Response({
            'status': 'ok',
            'message': 'Pick list completed',
            'picklist_id': picklist.picklist_id,
            'order_status': order_status,
            'time_taken': str(picklist.time_taken) if picklist.time_taken else None
        })

    @extend_schema(
        summary="Get pick list statistics",
        description="Get statistics about pick lists including success rates and timing.",
        responses={
            200: OpenApiResponse(
                description="Pick list statistics",
                examples=[
                    OpenApiExample(
                        name="Statistics Response",
                        value={
                            "total_picklists": 500,
                            "completed": 450,
                            "successful": 440,
                            "failed": 10,
                            "in_progress": 5,
                            "success_rate": 97.8,
                            "avg_time_taken": "00:04:30",
                            "today": {
                                "completed": 25,
                                "successful": 24
                            }
                        }
                    )
                ]
            )
        }
    )
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get pick list statistics for the customer."""
        customer = request.user.userprofile.customer
        picklists = PickList.objects.filter(customer=customer)

        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        completed = picklists.filter(successful__isnull=False)
        successful = picklists.filter(successful=True)
        failed = picklists.filter(successful=False)

        # Calculate success rate
        completed_count = completed.count()
        success_rate = round(
            (successful.count() / completed_count * 100) if completed_count > 0 else 0, 1
        )

        # Average time taken
        avg_time = completed.filter(time_taken__isnull=False).aggregate(
            avg=Avg('time_taken')
        )['avg']

        return Response({
            'total_picklists': picklists.count(),
            'completed': completed_count,
            'successful': successful.count(),
            'failed': failed.count(),
            'in_progress': picklists.filter(pick_started=True, successful__isnull=True).count(),
            'success_rate': success_rate,
            'avg_time_taken': str(avg_time) if avg_time else None,
            'today': {
                'completed': completed.filter(updated_at__gte=today).count(),
                'successful': successful.filter(updated_at__gte=today).count(),
            }
        })

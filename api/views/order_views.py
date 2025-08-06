from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import OrderSerializer
from orderpiqrApp.models import Order
from rest_framework import filters
from drf_spectacular.utils import extend_schema, OpenApiExample

@extend_schema(
    tags=["orders"],
    examples=[
        OpenApiExample(
            name="Order Example",
            description="An example order payload. order_code serves as a human-friendly identifier, while lines lists "
                        "the products in the order. Each product value represents the product's ID, which can be obtained "
                        "via the Product API.",
            value={
                "order_code": "ORDER-20250806-001",
                "notes": "Handle with care",
                "lines": [
                    {"quantity": 2, "product": 12345},
                    {"quantity": 5, "product": 67890}
                ]
            },
            request_only=True
        )
    ]
)
class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.none()  # ✅ Required for drf-spectacular
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['order_code']

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user.userprofile.customer)

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user.userprofile.customer)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

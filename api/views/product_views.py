from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from api.serializers import ProductSerializer
from orderpiqrApp.models import Product
from rest_framework import filters

from drf_spectacular.utils import extend_schema, OpenApiExample


@extend_schema(
    tags=["products"],
    examples=[
        OpenApiExample(
            name="Product example",
            description="An example product object. code contains the barcode or QR code used to identify the product. "
                        "location is an integer representing the product's physical storage location within the warehouse.",
            value={
                "code": "1234567",
                "description": "An example product",
                "location": 1234,
                "active": True,
                "customer": 1
            }
        )
    ]
)
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.none()  # ✅ Required for drf-spectacular
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['code', 'description']

    def get_queryset(self):
        return Product.objects.filter(customer=self.request.user.userprofile.customer)

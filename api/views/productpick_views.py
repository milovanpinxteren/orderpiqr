from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import ProductPickSerializer
from orderpiqrApp.models import ProductPick
from rest_framework import filters
from drf_spectacular.utils import extend_schema

@extend_schema(tags=["productpicks"])
class ProductPickViewSet(viewsets.ModelViewSet):
    queryset = ProductPick.objects.none()  # ✅ Required for drf-spectacular
    serializer_class = ProductPickSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['product__description', 'product__code']

    def get_queryset(self):
        return ProductPick.objects.filter(picklist__customer=self.request.user.userprofile.customer)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

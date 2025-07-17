from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from api.serializers import ProductSerializer
from orderpiqrApp.models import Product
from rest_framework import filters


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['code', 'description']

    def get_queryset(self):
        return Product.objects.filter(customer=self.request.user.userprofile.customer)


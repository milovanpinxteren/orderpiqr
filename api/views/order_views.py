from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import OrderSerializer
from orderpiqrApp.models import Order
from rest_framework import filters


class OrderViewSet(viewsets.ModelViewSet):
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

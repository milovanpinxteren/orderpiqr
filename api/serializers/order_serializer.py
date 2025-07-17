from rest_framework import serializers

from orderpiqrApp.models import Order
from .orderline_serializer import OrderLineSerializer

class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['customer']


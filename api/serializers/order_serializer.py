from rest_framework import serializers

from orderpiqrApp.models import Order
from .orderline_serializer import OrderLineSerializer

class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True)

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['customer']

    def create(self, validated_data):
        orderlines_data = validated_data.pop('lines', [])
        order = Order.objects.create(**validated_data)

        for line_data in orderlines_data:
            line_data['order'] = order
            serializer = OrderLineSerializer(data=line_data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

        return order
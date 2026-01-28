from rest_framework import serializers

from orderpiqrApp.models import OrderLine


class OrderLineSerializer(serializers.ModelSerializer):
    """
    Basic serializer for OrderLine model.
    """
    class Meta:
        model = OrderLine
        fields = ['id', 'order', 'product', 'quantity']
        read_only_fields = ['id']


class OrderLineDetailSerializer(serializers.ModelSerializer):
    """
    Extended serializer with product details included.
    """
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_description = serializers.CharField(source='product.description', read_only=True)
    product_location = serializers.CharField(source='product.location', read_only=True)

    class Meta:
        model = OrderLine
        fields = [
            'id',
            'order',
            'product',
            'product_code',
            'product_description',
            'product_location',
            'quantity',
        ]
        read_only_fields = ['id', 'product_code', 'product_description', 'product_location']


class OrderLineCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating order lines (used in nested order creation).
    """
    class Meta:
        model = OrderLine
        fields = ['product', 'quantity']

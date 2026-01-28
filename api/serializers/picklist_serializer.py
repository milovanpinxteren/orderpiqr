from rest_framework import serializers

from orderpiqrApp.models import PickList


class PickListSerializer(serializers.ModelSerializer):
    """
    Basic serializer for PickList model.
    """
    device_name = serializers.CharField(source='device.name', read_only=True)
    order_code = serializers.CharField(source='order.order_code', read_only=True, allow_null=True)
    product_count = serializers.SerializerMethodField(
        help_text="Number of products in this pick list"
    )

    class Meta:
        model = PickList
        fields = [
            'picklist_id',
            'customer',
            'order',
            'order_code',
            'picklist_code',
            'device',
            'device_name',
            'created_at',
            'updated_at',
            'pick_started',
            'pick_time',
            'time_taken',
            'successful',
            'notes',
            'product_count',
        ]
        read_only_fields = [
            'customer', 'created_at', 'updated_at', 'device_name',
            'order_code', 'product_count'
        ]

    def get_product_count(self, obj):
        """Count the number of products in this picklist."""
        return obj.products.count()


class PickListDetailSerializer(PickListSerializer):
    """
    Extended serializer with full product pick details.
    """
    products = serializers.SerializerMethodField(
        help_text="List of products to pick"
    )
    order_details = serializers.SerializerMethodField(
        help_text="Details of the source order"
    )

    class Meta(PickListSerializer.Meta):
        fields = PickListSerializer.Meta.fields + ['products', 'order_details']

    def get_products(self, obj):
        """Get all product picks with details."""
        return [
            {
                'id': pp.id,
                'product_id': pp.product.product_id,
                'product_code': pp.product.code,
                'product_description': pp.product.description,
                'product_location': pp.product.location,
                'quantity': pp.quantity,
                'successful': pp.successful,
                'time_taken': str(pp.time_taken) if pp.time_taken else None,
                'notes': pp.notes,
            }
            for pp in obj.products.select_related('product').all()
        ]

    def get_order_details(self, obj):
        """Get source order details if available."""
        if obj.order:
            return {
                'order_id': obj.order.order_id,
                'order_code': obj.order.order_code,
                'status': obj.order.status,
                'notes': obj.order.notes,
                'created_at': obj.order.created_at.isoformat(),
            }
        return None


class PickListCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating pick lists.
    """
    class Meta:
        model = PickList
        fields = ['order', 'picklist_code', 'device', 'notes']

from rest_framework import serializers
from django.db.models import Sum

from orderpiqrApp.models import Order, OrderLine
from .orderline_serializer import OrderLineSerializer, OrderLineDetailSerializer


class OrderSerializer(serializers.ModelSerializer):
    """
    Serializer for Order model with nested order lines.
    """
    lines = OrderLineSerializer(many=True)
    item_count = serializers.SerializerMethodField(
        help_text="Total number of items (sum of all line quantities)"
    )
    line_count = serializers.SerializerMethodField(
        help_text="Number of different products in the order"
    )

    class Meta:
        model = Order
        fields = [
            'order_id',
            'customer',
            'order_code',
            'created_at',
            'notes',
            'status',
            'queue_position',
            'completed_at',
            'lines',
            'item_count',
            'line_count',
        ]
        read_only_fields = ['customer', 'created_at', 'completed_at', 'item_count', 'line_count']

    def get_item_count(self, obj) -> int:
        """Calculate total items across all order lines."""
        return obj.lines.aggregate(total=Sum('quantity'))['total'] or 0

    def get_line_count(self, obj) -> int:
        """Count the number of order lines."""
        return obj.lines.count()

    def create(self, validated_data):
        orderlines_data = validated_data.pop('lines', [])
        order = Order.objects.create(**validated_data)

        for line_data in orderlines_data:
            line_data['order'] = order
            serializer = OrderLineSerializer(data=line_data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

        return order

    def update(self, instance, validated_data):
        """Update order, optionally replacing all lines."""
        orderlines_data = validated_data.pop('lines', None)

        # Update order fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # If lines were provided, replace them all
        if orderlines_data is not None:
            # Remove existing lines
            instance.lines.all().delete()
            # Create new lines
            for line_data in orderlines_data:
                OrderLine.objects.create(order=instance, **line_data)

        return instance


class OrderDetailSerializer(OrderSerializer):
    """
    Extended serializer with product details in order lines.
    """
    lines = OrderLineDetailSerializer(many=True, read_only=True)
    picklist_info = serializers.SerializerMethodField(
        help_text="Information about the associated pick list (if any)"
    )

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ['picklist_info']

    def get_picklist_info(self, obj) -> dict | None:
        """Get picklist information if order has been claimed."""
        picklist = obj.picklist_set.first()
        if picklist:
            return {
                'picklist_id': picklist.picklist_id,
                'picklist_code': picklist.picklist_code,
                'device_name': picklist.device.name if picklist.device else None,
                'pick_started': picklist.pick_started,
                'successful': picklist.successful,
                'time_taken': str(picklist.time_taken) if picklist.time_taken else None,
            }
        return None


class OrderCreateSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for creating orders.
    """
    lines = OrderLineSerializer(many=True)

    class Meta:
        model = Order
        fields = ['order_code', 'notes', 'lines']

    def create(self, validated_data):
        orderlines_data = validated_data.pop('lines', [])
        order = Order.objects.create(**validated_data)

        for line_data in orderlines_data:
            OrderLine.objects.create(order=order, **line_data)

        return order
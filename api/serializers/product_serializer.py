from rest_framework import serializers

from orderpiqrApp.models import Product, OrderLine
from orderpiqrApp.utils.inventory import is_inventory_enabled


class ProductSerializer(serializers.ModelSerializer):
    """
    Serializer for Product model with computed fields.
    """
    # Computed fields for additional context
    order_count = serializers.SerializerMethodField(
        help_text="Number of orders containing this product"
    )
    inventory_quantity = serializers.IntegerField(
        read_only=True,
        help_text="Current stock quantity (only shown when inventory management is enabled)"
    )

    class Meta:
        model = Product
        fields = [
            'product_id',
            'code',
            'description',
            'location',
            'active',
            'customer',
            'order_count',
            'inventory_quantity',
        ]
        read_only_fields = ['customer', 'order_count', 'inventory_quantity']

    def get_order_count(self, obj) -> int:
        """Count how many order lines reference this product."""
        return OrderLine.objects.filter(product=obj).count()

    def to_representation(self, instance):
        """Conditionally include inventory_quantity based on customer settings."""
        data = super().to_representation(instance)

        # Check if inventory is enabled for the customer
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            try:
                customer = request.user.userprofile.customer
                if not is_inventory_enabled(customer):
                    data.pop('inventory_quantity', None)
            except AttributeError:
                data.pop('inventory_quantity', None)
        else:
            data.pop('inventory_quantity', None)

        return data


class ProductDetailSerializer(ProductSerializer):
    """
    Extended serializer with recent order information.
    """
    recent_orders = serializers.SerializerMethodField(
        help_text="Recent orders containing this product"
    )

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + ['recent_orders']

    def get_recent_orders(self, obj) -> list[dict]:
        """Get the 5 most recent orders containing this product."""
        recent_lines = OrderLine.objects.filter(
            product=obj
        ).select_related('order').order_by('-order__created_at')[:5]

        return [
            {
                'order_id': line.order.order_id,
                'order_code': line.order.order_code,
                'quantity': line.quantity,
                'status': line.order.status,
                'created_at': line.order.created_at.isoformat(),
            }
            for line in recent_lines
        ]

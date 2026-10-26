from rest_framework import serializers

from orderpiqrApp.models import OrderLine


class PickAggregateFieldsMixin(serializers.Serializer):
    """Per-line pick aggregates, read from `self.context['pick_aggregates']` —
    the grouped query built once per request by `build_pick_aggregates` and
    injected by `OrderViewSet.get_serializer`.

    Deliberately None (not 0) when the context key is absent, so a bare
    `/api/orderlines/` call stays cheap: nothing here forces the view to run
    the aggregate query. Two order lines for the same product repeat the
    same (order, product) aggregate — do not sum them; the aggregate already
    describes the product's units across the whole order, not the line.
    """
    requested_quantity = serializers.IntegerField(
        source='quantity', read_only=True,
        help_text="Units requested on this line (alias of quantity).")
    picked_quantity = serializers.SerializerMethodField(
        help_text="Units recorded as picked for this (order, product). "
                   "Null when pick aggregates were not requested; two lines "
                   "of the same product repeat this figure — do not sum them.")
    short_quantity = serializers.SerializerMethodField(
        help_text="Units declared short for this (order, product). Same "
                   "null/repeat rules as picked_quantity.")
    lost_quantity = serializers.SerializerMethodField(
        help_text="Units never recorded as picked on a completed list for "
                   "this (order, product). Same null/repeat rules as picked_quantity.")

    def _aggregate_value(self, obj, key):
        aggregates = self.context.get('pick_aggregates')
        if aggregates is None:
            return None
        return aggregates.get((obj.order_id, obj.product_id), {}).get(key, 0)

    def get_picked_quantity(self, obj) -> int | None:
        return self._aggregate_value(obj, 'picked')

    def get_short_quantity(self, obj) -> int | None:
        return self._aggregate_value(obj, 'short')

    def get_lost_quantity(self, obj) -> int | None:
        return self._aggregate_value(obj, 'lost')


class OrderLineSerializer(PickAggregateFieldsMixin, serializers.ModelSerializer):
    """
    Basic serializer for OrderLine model.
    """
    class Meta:
        model = OrderLine
        fields = [
            'id', 'order', 'product', 'quantity',
            'requested_quantity', 'picked_quantity', 'short_quantity', 'lost_quantity',
        ]
        read_only_fields = [
            'id', 'requested_quantity', 'picked_quantity', 'short_quantity', 'lost_quantity',
        ]


class OrderLineDetailSerializer(PickAggregateFieldsMixin, serializers.ModelSerializer):
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
            'requested_quantity',
            'picked_quantity',
            'short_quantity',
            'lost_quantity',
        ]
        read_only_fields = [
            'id', 'product_code', 'product_description', 'product_location',
            'requested_quantity', 'picked_quantity', 'short_quantity', 'lost_quantity',
        ]


class OrderLineCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating order lines (used in nested order creation).
    """
    class Meta:
        model = OrderLine
        fields = ['product', 'quantity']

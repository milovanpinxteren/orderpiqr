from django.db import IntegrityError, transaction
from rest_framework import serializers

from orderpiqrApp.models import Product, OrderLine
from orderpiqrApp.utils.inventory import is_inventory_enabled
from orderpiqrApp.utils.products import code_conflict, set_alias_codes, set_primary_code


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
    # write_only: the model attribute is a related manager, which ListField
    # can't render — reads are added in to_representation instead.
    barcodes = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        write_only=True,
        help_text="Alternative scan codes for this product (e.g. a superseded EAN "
                  "still on physical stock). Provided list replaces the current set. "
                  "Exception: when the same request also changes `code`, the replaced "
                  "primary code is kept as a barcode automatically (never forget a "
                  "code) and appears in the list on top of what was provided."
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
            'barcodes',
        ]
        read_only_fields = ['customer', 'order_count', 'inventory_quantity']

    def get_order_count(self, obj) -> int:
        """Count how many order lines reference this product."""
        return OrderLine.objects.filter(product=obj).count()

    def _customer(self):
        request = self.context.get('request')
        return request.user.userprofile.customer if request else None

    def validate(self, attrs):
        """Every code — primary and alias — must be unique within the customer
        across both primary codes and barcode aliases."""
        customer = self._customer()
        if customer is None:
            return attrs

        codes = []
        if 'code' in attrs:
            codes.append(attrs['code'])
        codes.extend(attrs.get('barcodes') or [])

        seen = set()
        for code in codes:
            code = str(code).strip()
            if not code:
                raise serializers.ValidationError({'barcodes': 'Barcodes cannot be empty.'})
            if code in seen:
                raise serializers.ValidationError(
                    {'barcodes': f'Duplicate code "{code}" in request.'})
            seen.add(code)
            if code_conflict(customer, code, exclude_product=self.instance):
                raise serializers.ValidationError(
                    {'code' if 'code' in attrs and code == attrs['code'] else 'barcodes':
                     f'Code "{code}" is already in use by another product.'})
        return attrs

    def create(self, validated_data):
        barcodes = validated_data.pop('barcodes', None)
        try:
            with transaction.atomic():
                product = super().create(validated_data)
                if barcodes:
                    set_alias_codes(product, barcodes)
        except IntegrityError:
            # validate() checks conflicts, but a concurrent write can still win
            # the race to the unique constraint — report it, don't 500.
            raise serializers.ValidationError(
                {'barcodes': 'A code in this request was just taken by another product.'})
        return product

    def update(self, instance, validated_data):
        barcodes = validated_data.pop('barcodes', None)
        new_code = validated_data.pop('code', None)
        try:
            with transaction.atomic():
                product = super().update(instance, validated_data)
                if barcodes is not None:
                    set_alias_codes(product, barcodes)
                if new_code is not None:
                    # Never forget a code: the old primary stays scannable as an
                    # alias, so labels and printed picklists from before the
                    # change keep working.
                    set_primary_code(product, new_code)
        except IntegrityError:
            # E.g. the demoted old primary already exists as another product's
            # alias (possible via surfaces that predate code_conflict checks).
            raise serializers.ValidationError(
                {'code': 'The replaced code conflicts with an existing barcode of another product.'})
        return product

    def to_representation(self, instance):
        """Conditionally include inventory_quantity based on customer settings."""
        data = super().to_representation(instance)
        # .all() (not values_list) so the ViewSet's prefetch cache is used on lists.
        data['barcodes'] = sorted(barcode.code for barcode in instance.barcodes.all())

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

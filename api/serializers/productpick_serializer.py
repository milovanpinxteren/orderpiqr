from rest_framework import serializers

from orderpiqrApp.models import ProductPick


def _translate_successful(attrs):
    """Map a legacy posted `successful` onto `outcome`.

    `outcome` is the source of truth (the model derives `successful` from it on
    save), so a posted boolean becomes an outcome — unless the caller sent an
    explicit outcome, which wins.
    """
    if 'outcome' in attrs:
        attrs.pop('successful', None)
    elif 'successful' in attrs:
        attrs['outcome'] = ProductPick.outcome_from_successful(attrs.pop('successful'))
    return attrs


class ProductPickSerializer(serializers.ModelSerializer):
    """
    Basic serializer for ProductPick model.
    """
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_description = serializers.CharField(source='product.description', read_only=True)
    product_location = serializers.CharField(source='product.location', read_only=True)
    picklist_code = serializers.CharField(source='picklist.picklist_code', read_only=True)

    class Meta:
        model = ProductPick
        fields = [
            'id',
            'picklist',
            'picklist_code',
            'product',
            'product_code',
            'product_description',
            'product_location',
            'quantity',
            'time_taken',
            'successful',
            'outcome',
            'short_reason',
            'notes',
        ]
        read_only_fields = [
            'id', 'product_code', 'product_description',
            'product_location', 'picklist_code'
        ]

    def validate(self, attrs):
        return _translate_successful(attrs)


class ProductPickUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating product pick status during picking operations.
    """
    class Meta:
        model = ProductPick
        fields = ['successful', 'outcome', 'short_reason', 'time_taken', 'notes']

    def validate(self, attrs):
        return _translate_successful(attrs)


class ProductPickBulkUpdateSerializer(serializers.Serializer):
    """
    Serializer for bulk updating multiple product picks.
    """
    picks = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of pick updates with 'id', 'successful' or 'outcome', and optional 'notes'"
    )

    def validate_picks(self, value):
        for pick in value:
            if 'id' not in pick:
                raise serializers.ValidationError("Each pick must have an 'id' field")
            if 'successful' not in pick and 'outcome' not in pick:
                raise serializers.ValidationError(
                    "Each pick must have a 'successful' or 'outcome' field")
        return value

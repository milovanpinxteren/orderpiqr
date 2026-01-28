from rest_framework import serializers

from orderpiqrApp.models import ProductPick


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
            'notes',
        ]
        read_only_fields = [
            'id', 'product_code', 'product_description',
            'product_location', 'picklist_code'
        ]


class ProductPickUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating product pick status during picking operations.
    """
    class Meta:
        model = ProductPick
        fields = ['successful', 'time_taken', 'notes']


class ProductPickBulkUpdateSerializer(serializers.Serializer):
    """
    Serializer for bulk updating multiple product picks.
    """
    picks = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of pick updates with 'id', 'successful', and optional 'notes'"
    )

    def validate_picks(self, value):
        for pick in value:
            if 'id' not in pick:
                raise serializers.ValidationError("Each pick must have an 'id' field")
            if 'successful' not in pick:
                raise serializers.ValidationError("Each pick must have a 'successful' field")
        return value

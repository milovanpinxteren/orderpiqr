from rest_framework import serializers

from orderpiqrApp.models import InventoryLog, Product


class InventoryLogSerializer(serializers.ModelSerializer):
    """
    Serializer for InventoryLog model with related fields.
    """
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_description = serializers.CharField(source='product.description', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True, allow_null=True)
    user_full_name = serializers.SerializerMethodField()
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)
    quantity_change = serializers.ReadOnlyField()
    change_type_display = serializers.CharField(source='get_change_type_display', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)

    class Meta:
        model = InventoryLog
        fields = [
            'log_id',
            'product',
            'product_code',
            'product_description',
            'user',
            'username',
            'user_full_name',
            'device',
            'device_name',
            'old_quantity',
            'new_quantity',
            'quantity_change',
            'change_type',
            'change_type_display',
            'reason',
            'reason_display',
            'notes',
            'created_at',
        ]
        read_only_fields = ['log_id', 'created_at']

    def get_user_full_name(self, obj) -> str:
        """Get the user's full name or username."""
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return None


class InventoryModifySerializer(serializers.Serializer):
    """
    Serializer for inventory modification requests.
    """
    product_id = serializers.IntegerField(
        help_text="ID of the product to modify"
    )
    change_type = serializers.ChoiceField(
        choices=InventoryLog.ChangeType.choices,
        help_text="Type of change: 'set' for absolute value, 'adjust' for relative change"
    )
    value = serializers.IntegerField(
        help_text="The quantity value: new absolute quantity for 'set', or delta for 'adjust'"
    )
    reason = serializers.ChoiceField(
        choices=InventoryLog.Reason.choices,
        help_text="Reason for the inventory change"
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional notes about the change"
    )

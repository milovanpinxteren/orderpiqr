from rest_framework import serializers

from orderpiqrApp.models import Device


class DeviceSerializer(serializers.ModelSerializer):
    """
    Serializer for Device model.
    """
    username = serializers.CharField(source='user.username', read_only=True, allow_null=True)
    recent_activity = serializers.SerializerMethodField(
        help_text="Summary of recent picking activity"
    )

    class Meta:
        model = Device
        fields = [
            'device_id',
            'name',
            'description',
            'device_fingerprint',
            'user',
            'username',
            'customer',
            'last_login',
            'lists_picked',
            'recent_activity',
        ]
        read_only_fields = ['customer', 'lists_picked', 'username', 'recent_activity']

    def get_recent_activity(self, obj):
        """Get summary of recent picking activity."""
        recent_picklists = obj.picklist_set.order_by('-created_at')[:5]
        return [
            {
                'picklist_id': pl.picklist_id,
                'picklist_code': pl.picklist_code,
                'order_code': pl.order.order_code if pl.order else None,
                'created_at': pl.created_at.isoformat(),
                'successful': pl.successful,
            }
            for pl in recent_picklists
        ]


class DeviceCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/registering a new device.
    """
    class Meta:
        model = Device
        fields = ['name', 'description', 'device_fingerprint']


class DeviceStatsSerializer(serializers.Serializer):
    """
    Serializer for device statistics.
    """
    device_id = serializers.IntegerField()
    name = serializers.CharField()
    total_picks = serializers.IntegerField()
    successful_picks = serializers.IntegerField()
    failed_picks = serializers.IntegerField()
    success_rate = serializers.FloatField()
    avg_time_per_pick = serializers.DurationField(allow_null=True)
    last_active = serializers.DateTimeField(allow_null=True)

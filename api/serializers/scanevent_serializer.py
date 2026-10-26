from rest_framework import serializers

from orderpiqrApp.models import ScanEvent


class ScanEventSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for ScanEvent: pick-flow health events (a scan that
    failed, a list that was rejected, a manual override) written best-effort
    from the scan endpoints and the picker client.
    """
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)
    # occurred_at is a model property, not a column: it's client_ts when the
    # device sent one, falling back to created_at (server receipt time) for
    # events logged before the client timestamped them, or logged server-side.
    occurred_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ScanEvent
        fields = [
            'id',
            'event_type',
            'severity',
            'reason',
            'scanned_code',
            'picklist_code',
            'message',
            'build_id',
            'device',
            'device_name',
            'client_ts',
            'created_at',
            'occurred_at',
        ]
        read_only_fields = fields

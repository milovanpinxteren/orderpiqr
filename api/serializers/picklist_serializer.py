from rest_framework import serializers

from orderpiqrApp.models import PickList


class PickListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickList
        fields = '__all__'

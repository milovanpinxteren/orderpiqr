from rest_framework import serializers

from orderpiqrApp.models import OrderLine


class OrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderLine
        fields = '__all__'

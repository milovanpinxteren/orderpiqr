from rest_framework import serializers

from orderpiqrApp.models import ProductPick

class ProductPickSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductPick
        fields = '__all__'

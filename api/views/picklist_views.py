from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import PickListSerializer
from orderpiqrApp.models import PickList
from rest_framework import filters


class PickListViewSet(viewsets.ModelViewSet):
    serializer_class = PickListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['picklist_code', 'notes']

    def get_queryset(self):
        return PickList.objects.filter(customer=self.request.user.userprofile.customer)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Delete not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

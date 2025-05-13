from django.contrib import admin

from orderpiqrApp.models import Device


class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'last_login', 'lists_picked', 'customer')
    search_fields = ['name', 'description']

    def get_queryset(self, request):
        """Override queryset to filter by company"""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            return queryset.filter(customer__user=request.user)  # Filter devices for the company of the logged-in user
        return queryset.none()

admin.site.register(Device, DeviceAdmin)

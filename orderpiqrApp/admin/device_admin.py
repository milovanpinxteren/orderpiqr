from django.contrib import admin

from orderpiqrApp.models import Device


class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'customer', 'last_login', 'lists_picked',
                    'display_mode', 'os', 'archived')
    list_filter = ('customer', 'archived', 'display_mode', 'os', 'browser')
    search_fields = ['name', 'description', 'device_fingerprint']
    list_select_related = ('customer',)
    date_hierarchy = 'last_login'
    # Most recently active first: the question asked here is nearly always
    # "who is picking now", not "which device was registered first".
    ordering = ('-last_login',)

    def get_queryset(self, request):
        """Override queryset to filter by company"""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            return queryset.filter(customer=request.user.userprofile.customer)  # Filter devices for the company of the logged-in user
        return queryset.none()

admin.site.register(Device, DeviceAdmin)

from django.contrib import admin

from orderpiqrApp.models import ScanEvent


class ScanEventAdmin(admin.ModelAdmin):
    """Read-only log view: ScanEvent rows are written by the scan endpoints and
    the picker client, never by hand."""

    list_display = ('created_at', 'customer', 'event_type', 'scanned_code', 'picklist_code', 'device')
    list_filter = ('event_type',)
    search_fields = ('scanned_code', 'picklist_code')
    readonly_fields = ('customer', 'device', 'event_type', 'scanned_code',
                       'picklist_code', 'message', 'created_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        """Filter scan events by company, mirroring PickListAdmin."""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            return queryset.filter(customer=request.user.userprofile.customer)
        return queryset.none()


admin.site.register(ScanEvent, ScanEventAdmin)

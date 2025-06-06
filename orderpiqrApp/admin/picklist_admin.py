from django.contrib import admin

from orderpiqrApp.models import PickList, ProductPick


class ProductPickInline(admin.TabularInline):
    model = ProductPick
    extra = 0  # No empty rows for adding new product picks
    fields = ('product', 'quantity', 'time_taken', 'successful')

class PickListAdmin(admin.ModelAdmin):
    list_display = ('picklist_code', 'device', 'pick_time', 'time_taken', 'successful')
    search_fields = ['device__name', 'pick_time']
    inlines = [ProductPickInline]  # Add ProductPickInline to the admin interface


    def get_queryset(self, request):
        """Override queryset to filter picklists by company"""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            return queryset.filter(device__customer=request.user.userprofile.customer)  # Filter picklists by the company of the logged-in user
        return queryset.none()

admin.site.register(PickList, PickListAdmin)

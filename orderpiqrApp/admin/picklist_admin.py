from django.contrib import admin
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from orderpiqrApp.models import PickList, ProductPick


class ProductPickInline(admin.TabularInline):
    model = ProductPick
    extra = 0  # No empty rows for adding new product picks
    fields = ('product', 'quantity', 'time_taken', 'outcome', 'short_reason', 'successful')
    # Derived from outcome in save(); editing it directly would be overwritten.
    readonly_fields = ('successful',)
    # A plain select renders every product of every customer once per row, so a
    # forty-line picklist used to ship tens of thousands of options to open.
    autocomplete_fields = ('product',)


class PickListAdmin(admin.ModelAdmin):
    list_display = ('picklist_code', 'customer', 'device', 'created_at',
                    'time_taken', 'line_count', 'successful', 'archived')
    list_filter = ('customer', 'archived', 'successful', 'created_at')
    # 'pick_time' used to sit in here. It is a DateTimeField, and the admin
    # turns every search term into an icontains against each search field, so
    # any term that was not date-shaped broke the query instead of just
    # matching nothing.
    search_fields = ['picklist_code', 'device__name', 'order__order_code']
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('customer', 'device')
    inlines = [ProductPickInline]  # Add ProductPickInline to the admin interface

    def get_queryset(self, request):
        """Override queryset to filter picklists by company"""
        queryset = super().get_queryset(request)
        if not request.user.is_superuser:
            if request.user.groups.filter(name='companyadmin').exists():
                # Filter picklists by the company of the logged-in user
                queryset = queryset.filter(customer=request.user.userprofile.customer)
            else:
                return queryset.none()
        return queryset.annotate(n_lines=Count('products'))

    def line_count(self, obj):
        return obj.n_lines
    line_count.short_description = _('Lines')
    line_count.admin_order_field = 'n_lines'


admin.site.register(PickList, PickListAdmin)

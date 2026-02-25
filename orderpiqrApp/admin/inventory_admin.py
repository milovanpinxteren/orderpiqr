from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from orderpiqrApp.models import InventoryLog


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'product_code', 'quantity_change_badge',
        'change_type', 'reason', 'user_name', 'device_name'
    )
    list_filter = ('change_type', 'reason', 'created_at', 'product__customer')
    search_fields = ('product__code', 'product__description', 'notes', 'user__username')
    date_hierarchy = 'created_at'
    readonly_fields = (
        'product', 'user', 'device', 'old_quantity', 'new_quantity',
        'change_type', 'reason', 'notes', 'created_at', 'source_picklist'
    )
    raw_id_fields = ('product', 'user', 'device', 'source_picklist')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def product_code(self, obj):
        return obj.product.code
    product_code.short_description = _('Product')
    product_code.admin_order_field = 'product__code'

    def quantity_change_badge(self, obj):
        change = obj.quantity_change
        if change > 0:
            color = '#118f11'
            text = f'+{change}'
        elif change < 0:
            color = '#dc3545'
            text = str(change)
        else:
            color = '#6c757d'
            text = '0'
        return format_html(
            '<span style="color:{}; font-weight:600;">{} &rarr; {} ({})</span>',
            color, obj.old_quantity, obj.new_quantity, text
        )
    quantity_change_badge.short_description = _('Change')
    quantity_change_badge.admin_order_field = 'new_quantity'

    def user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return '-'
    user_name.short_description = _('User')
    user_name.admin_order_field = 'user__username'

    def device_name(self, obj):
        if obj.device:
            return obj.device.name
        return '-'
    device_name.short_description = _('Device')
    device_name.admin_order_field = 'device__name'

    fieldsets = (
        (_('Product'), {
            'fields': ('product',),
        }),
        (_('Change Details'), {
            'fields': ('old_quantity', 'new_quantity', 'change_type', 'reason', 'notes'),
        }),
        (_('Metadata'), {
            'fields': ('user', 'device', 'created_at', 'source_picklist'),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('product', 'user', 'device', 'source_picklist')

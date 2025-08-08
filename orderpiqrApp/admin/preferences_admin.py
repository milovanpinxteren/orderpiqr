from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from orderpiqrApp.models import SettingDefinition, CustomerSettingValue


@admin.register(SettingDefinition)
class SettingDefinitionAdmin(admin.ModelAdmin):
    list_display = ('key', 'label', 'setting_type', 'default_value')
    search_fields = ['key', 'label', 'help_text']
    list_filter = ['setting_type']
    ordering = ['key']
    fieldsets = (
        (_('General Info'), {
            'fields': ('key', 'label', 'setting_type', 'default_value'),
        }),
        (_('Advanced'), {
            'fields': ('help_text',),
            'classes': ('collapse',),
        }),
    )


@admin.register(CustomerSettingValue)
class CustomerSettingValueAdmin(admin.ModelAdmin):
    list_display = ('customer', 'definition', 'value')
    search_fields = ['customer__name', 'definition__key', 'value']
    list_filter = ['definition__key']
    ordering = ['customer', 'definition']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            return queryset.filter(customer=request.user.userprofile.customer)
        return queryset.none()

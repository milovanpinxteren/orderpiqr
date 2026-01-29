from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from orderpiqrApp.models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'status_badge', 'email_type', 'subject', 'to_emails', 'from_email')
    list_filter = ('status', 'email_type', 'created_at')
    search_fields = ('subject', 'to_emails', 'from_email', 'error_message')
    date_hierarchy = 'created_at'
    readonly_fields = (
        'subject', 'from_email', 'to_emails', 'body_text', 'body_html_preview',
        'status', 'error_message', 'email_type', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def status_badge(self, obj):
        color = '#118f11' if obj.status == 'sent' else '#dc3545'
        return format_html(
            '<span style="color:{}; font-weight:600;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def body_html_preview(self, obj):
        if not obj.body_html:
            return '-'
        return format_html(
            '<iframe srcdoc="{}" style="width:100%;height:400px;border:1px solid #ddd;border-radius:4px;"></iframe>',
            obj.body_html.replace('"', '&quot;')
        )
    body_html_preview.short_description = _('HTML Preview')

    fieldsets = (
        (_('Delivery'), {
            'fields': ('status', 'error_message', 'email_type', 'created_at'),
        }),
        (_('Message'), {
            'fields': ('subject', 'from_email', 'to_emails', 'body_text', 'body_html_preview'),
        }),
    )

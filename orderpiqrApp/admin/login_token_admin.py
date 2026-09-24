from django.contrib import admin

from orderpiqrApp.models import PickerLoginToken


class PickerLoginTokenAdmin(admin.ModelAdmin):
    """Read-and-revoke only, with one exception: tokens are issued from
    manage/profile, where the raw value can be rendered as a QR, and nothing
    here can recover a token since only its hash is stored. ``start_page``
    stays editable because it is not part of the printed code — correcting it
    saves reprinting and redistributing a sheet."""

    list_display = ('user', 'customer', 'start_page', 'created', 'expires_at',
                    'revoked_at', 'last_used_at', 'use_count')
    list_filter = ('customer', 'revoked_at', 'start_page')
    search_fields = ['user__username']
    readonly_fields = ('user', 'customer', 'key_hash', 'created_by', 'created',
                       'expires_at', 'last_used_at', 'use_count')
    actions = ['revoke_selected']

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            return queryset.filter(customer=request.user.userprofile.customer)
        return queryset.none()

    @admin.action(description="Revoke selected login QRs")
    def revoke_selected(self, request, queryset):
        revoked = 0
        for token in queryset.filter(revoked_at__isnull=True):
            token.revoke()
            revoked += 1
        self.message_user(request, f"{revoked} login QR(s) revoked.")


admin.site.register(PickerLoginToken, PickerLoginTokenAdmin)

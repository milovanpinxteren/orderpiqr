from django.contrib import admin

from integrations_woocommerce.models import PairingToken, WooCommerceStore


@admin.register(WooCommerceStore)
class WooCommerceStoreAdmin(admin.ModelAdmin):
    list_display = ('store_url', 'store_name', 'connection', 'woocommerce_version',
                    'plugin_version', 'last_poll_at', 'connected_at')
    search_fields = ('store_url', 'store_name')
    readonly_fields = ('encrypted_consumer_key', 'encrypted_consumer_secret',
                       'plugin_token_hash', 'connected_at')


@admin.register(PairingToken)
class PairingTokenAdmin(admin.ModelAdmin):
    list_display = ('customer', 'created_at', 'expires_at', 'used_at')
    list_filter = ('used_at',)
    readonly_fields = ('token_hash', 'created_at')

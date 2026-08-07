from django.contrib import admin

from integrations_shopify.models import ShopifyShop


@admin.register(ShopifyShop)
class ShopifyShopAdmin(admin.ModelAdmin):
    list_display = ('shop_domain', 'shop_name', 'connection', 'installed_at', 'uninstalled_at')
    readonly_fields = ('encrypted_access_token', 'encrypted_refresh_token')

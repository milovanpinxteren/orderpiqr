from django.contrib import admin

from integrations.models import (
    Connection, ExternalOrderLink, ProductLink, SyncOutbox, WebhookInbox,
)


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ('connection_id', 'platform', 'customer', 'name', 'status', 'created_at')
    list_filter = ('platform', 'status')


@admin.register(WebhookInbox)
class WebhookInboxAdmin(admin.ModelAdmin):
    list_display = ('id', 'connection', 'topic', 'status', 'attempts', 'received_at')
    list_filter = ('status', 'topic')
    readonly_fields = ('payload', 'received_at', 'processed_at')


@admin.register(SyncOutbox)
class SyncOutboxAdmin(admin.ModelAdmin):
    list_display = ('id', 'connection', 'action', 'order', 'status', 'attempts', 'next_attempt_at')
    list_filter = ('status', 'action')


@admin.register(ProductLink)
class ProductLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'connection', 'external_variant_id', 'product', 'match_method', 'locked')
    list_filter = ('match_method', 'locked')
    search_fields = ('external_variant_id', 'identifier_value', 'title')


@admin.register(ExternalOrderLink)
class ExternalOrderLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'connection', 'external_order_number', 'order', 'created_at')
    search_fields = ('external_order_id', 'external_order_number')

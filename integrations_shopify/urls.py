from django.urls import path

from integrations_shopify import views

app_name = 'shopify'

urlpatterns = [
    path('app/', views.app_entry, name='app_entry'),
    # Shopify delivers without a trailing slash; APPEND_SLASH can't redirect POSTs
    path('webhooks', views.webhook, name='webhook'),
    path('webhooks/', views.webhook, name='webhook_slash'),
    path('api/status/', views.api_status, name='api_status'),
    path('api/config/', views.api_update_config, name='api_config'),
    path('api/sync-products/', views.api_sync_products, name='api_sync_products'),
    path('api/unresolved/', views.api_unresolved, name='api_unresolved'),
    path('api/map-product/', views.api_map_product, name='api_map_product'),
    path('api/picker-password/', views.api_set_picker_password, name='api_picker_password'),
    path('api/link-account/', views.api_link_account, name='api_link_account'),
]

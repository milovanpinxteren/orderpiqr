from django.urls import path

from integrations_woocommerce import views

app_name = 'woocommerce'

# WordPress delivers POSTs without a trailing slash; APPEND_SLASH can't
# redirect POSTs, so every route is registered both ways.
urlpatterns = [
    path('connect', views.connect, name='connect'),
    path('connect/', views.connect, name='connect_slash'),
    path('webhooks', views.webhook, name='webhook'),
    path('webhooks/', views.webhook, name='webhook_slash'),
    path('disconnect', views.disconnect, name='disconnect'),
    path('disconnect/', views.disconnect, name='disconnect_slash'),
    path('status', views.status, name='status'),
    path('status/', views.status, name='status_slash'),
]

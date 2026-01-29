"""
URL configuration for orderpiqr project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from orderpiqrApp.views.main_views import *
from orderpiqrApp.views.queue_views import (
    queue_display,
    queue_display_partial,
    queue_picker,
    queue_picker_partial,
    queue_claim_order,
    queue_manage,
    queue_manage_partial,
    queue_add_order,
    queue_remove_order,
    queue_reorder,
    queue_move_order,
    queue_unlock_order,
)
from orderpiqrApp.views.manage_views import (
    dashboard,
    products_list,
    product_create,
    product_edit,
    product_delete,
    products_bulk_action,
    product_inline_edit,
    products_import,
    products_export,
    orders_list,
    order_create,
    order_edit,
    order_delete,
    orders_import,
    queue_manage as manage_queue,
    picklists_list,
    picklist_detail,
    devices_list,
    profile,
    settings_view,
    logout_view,
)

urlpatterns = [
    path('', index, name='index'),

    # Queue Display (Tablet/PC with QR codes)
    path('queue/display/', queue_display, name='queue_display'),
    path('queue/display/partial/', queue_display_partial, name='queue_display_partial'),

    # Queue Picker (Mobile - tap to select)
    path('queue/', queue_picker, name='queue_picker'),
    path('queue/partial/', queue_picker_partial, name='queue_picker_partial'),
    path('queue/claim/<int:order_id>/', queue_claim_order, name='queue_claim_order'),

    # Queue Management (Admin)
    path('queue/manage/', queue_manage, name='queue_manage'),
    path('queue/manage/partial/', queue_manage_partial, name='queue_manage_partial'),
    path('queue/add/<int:order_id>/', queue_add_order, name='queue_add_order'),
    path('queue/remove/<int:order_id>/', queue_remove_order, name='queue_remove_order'),
    path('queue/unlock/<int:order_id>/', queue_unlock_order, name='queue_unlock_order'),
    path('queue/reorder/', queue_reorder, name='queue_reorder'),
    path('queue/move/<int:order_id>/<str:direction>/', queue_move_order, name='queue_move_order'),

    # Custom Admin Management Interface
    path('manage/', dashboard, name='manage_dashboard'),

    # Products Management
    path('manage/products/', products_list, name='manage_products'),
    path('manage/products/create/', product_create, name='manage_product_create'),
    path('manage/products/<int:product_id>/edit/', product_edit, name='manage_product_edit'),
    path('manage/products/<int:product_id>/delete/', product_delete, name='manage_product_delete'),
    path('manage/products/<int:product_id>/inline-edit/', product_inline_edit, name='manage_product_inline_edit'),
    path('manage/products/bulk-action/', products_bulk_action, name='manage_products_bulk_action'),
    path('manage/products/import/', products_import, name='manage_products_import'),
    path('manage/products/export/', products_export, name='manage_products_export'),

    # Orders Management
    path('manage/orders/', orders_list, name='manage_orders'),
    path('manage/orders/create/', order_create, name='manage_order_create'),
    path('manage/orders/<int:order_id>/edit/', order_edit, name='manage_order_edit'),
    path('manage/orders/<int:order_id>/delete/', order_delete, name='manage_order_delete'),
    path('manage/orders/import/', orders_import, name='manage_orders_import'),

    # Queue Management (in new admin)
    path('manage/queue/', manage_queue, name='manage_queue'),

    # Picklists (Read-only)
    path('manage/picklists/', picklists_list, name='manage_picklists'),
    path('manage/picklists/<int:picklist_id>/', picklist_detail, name='manage_picklist_detail'),

    # Devices (Read-only)
    path('manage/devices/', devices_list, name='manage_devices'),

    # Profile & Settings
    path('manage/profile/', profile, name='manage_profile'),
    path('manage/settings/', settings_view, name='manage_settings'),
    path('manage/logout/', logout_view, name='manage_logout'),
]

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
    path('queue/reorder/', queue_reorder, name='queue_reorder'),
    path('queue/move/<int:order_id>/<str:direction>/', queue_move_order, name='queue_move_order'),
]

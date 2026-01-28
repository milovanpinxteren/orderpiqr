from django.urls import path, include
from rest_framework.routers import DefaultRouter

from api.views.product_views import ProductViewSet
from api.views.order_views import OrderViewSet
from api.views.orderline_views import OrderLineViewSet
from api.views.picklist_views import PickListViewSet
from api.views.productpick_views import ProductPickViewSet
from api.views.device_views import DeviceViewSet
from api.views.queue_views import (
    queue_list,
    queue_stats,
    queue_add_order,
    queue_remove_order,
    queue_claim_order,
    queue_reorder,
    queue_move_order,
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'orderlines', OrderLineViewSet, basename='orderline')
router.register(r'picklists', PickListViewSet, basename='picklist')
router.register(r'productpicks', ProductPickViewSet, basename='productpick')
router.register(r'devices', DeviceViewSet, basename='device')


urlpatterns = [
    path('', include(router.urls)),

    # Queue management endpoints
    path('queue/', queue_list, name='queue-list'),
    path('queue/stats/', queue_stats, name='queue-stats'),
    path('queue/add/<int:order_id>/', queue_add_order, name='queue-add-order'),
    path('queue/remove/<int:order_id>/', queue_remove_order, name='queue-remove-order'),
    path('queue/claim/<int:order_id>/', queue_claim_order, name='queue-claim-order'),
    path('queue/reorder/', queue_reorder, name='queue-reorder'),
    path('queue/move/<int:order_id>/<str:direction>/', queue_move_order, name='queue-move-order'),
]

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from api.views.product_views import ProductViewSet
from api.views.order_views import OrderViewSet
from api.views.orderline_views import OrderLineViewSet
from api.views.picklist_views import PickListViewSet
from api.views.productpick_views import ProductPickViewSet

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'orderlines', OrderLineViewSet, basename='orderline')
router.register(r'picklists', PickListViewSet, basename='picklist')
router.register(r'productpicks', ProductPickViewSet, basename='productpick')


urlpatterns = [
    path('', include(router.urls)),
]

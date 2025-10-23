from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import JavaScriptCatalog

from orderpiqr.views import *
from orderpiqrApp.views import scan_picklist, complete_picklist, product_pick
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from django.views.generic import TemplateView
from django.views.static import serve
from django.conf import settings
from django.urls import re_path
from django.contrib.admin.views.decorators import staff_member_required
from orderpiqrApp.views.auth.signup_view import signup

from django.contrib import admin

admin.site.index_template = "admin/custom_index.html"

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),  # Enables the language switcher post endpoint
    path('jsi18n/', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    path('signup/', signup, name='signup'),
    path('login/', custom_login, name='login'),
    path('name-entry/', name_entry, name='name_entry'),
    path('admin/loginas/', include('loginas.urls')),
    path('admin/download_batch_qr_pdf/<str:file_name>/', download_batch_qr_pdf, name='download_batch_qr_pdf'),
    path('orderpiqr/scan-picklist', scan_picklist, name='scan-picklist'),  # Keep this outside of i18n to enable POST
    path('orderpiqr/product-pick', product_pick, name='product-pick'),
    path('orderpiqr/complete-picklist', complete_picklist, name='complete-picklist'),
    # Keep this outside of i18n to enable POST
    path('offline/', TemplateView.as_view(template_name='offline.html'), name='offline'),
    re_path(r'^serviceWorker\.js$', serve, {'document_root': settings.BASE_DIR, 'path': 'serviceWorker.js'}),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Swagger UI
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # Optional: Redoc UI
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/', include('api.urls')),  # your actual API

]

urlpatterns += i18n_patterns(
    path("admin/metrics/picklists-this-month.json", staff_member_required(picklists_this_month_cumulative),
         name="admin-picklists-this-month", ),
    path('admin/', admin.site.urls),
    path('', root_redirect, name='root_redirect'),
    path('orderpiqr/', include('orderpiqrApp.urls')),
)

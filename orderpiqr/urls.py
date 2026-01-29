from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import JavaScriptCatalog

from orderpiqr.views import *
from orderpiqrApp.views import scan_picklist, complete_picklist, product_pick
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from api.views.documentation_views import documentation_view
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

    # Password Reset URLs
    path('password-reset/',
         CustomPasswordResetView.as_view(),
         name='password_reset'),
    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='registration/password_reset_done.html'
         ),
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='registration/password_reset_confirm.html'
         ),
         name='password_reset_confirm'),
    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='registration/password_reset_complete.html'
         ),
         name='password_reset_complete'),
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

    # Markdown documentation
    path('api/documentation/', documentation_view, {'language': 'en'}, name='api-documentation'),
    path('api/documentation/en/', documentation_view, {'language': 'en'}, name='api-documentation-en'),
    path('api/documentation/nl/', documentation_view, {'language': 'nl'}, name='api-documentation-nl'),

    path('api/', include('api.urls')),  # your actual API

]

urlpatterns += i18n_patterns(
    path("admin/metrics/picklists-this-month.json", staff_member_required(picklists_this_month_cumulative),
         name="admin-picklists-this-month", ),
    path('admin/', admin.site.urls),
    path('', root_redirect, name='root_redirect'),
    path('orderpiqr/', include('orderpiqrApp.urls')),
)

# Custom error handlers
handler400 = 'orderpiqr.views.error_400'
handler403 = 'orderpiqr.views.error_403'
handler404 = 'orderpiqr.views.error_404'
handler500 = 'orderpiqr.views.error_500'

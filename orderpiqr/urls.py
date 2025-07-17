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
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import JavaScriptCatalog

from orderpiqr.views import *
from orderpiqrApp.views import scan_picklist, complete_picklist
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),  # Enables the language switcher post endpoint
    path('jsi18n/', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    path('login/', custom_login, name='login'),
    path('name-entry/', name_entry, name='name_entry'),
    path('admin/loginas/', include('loginas.urls')),
    path('admin/download_batch_qr_pdf/<str:file_name>/', download_batch_qr_pdf, name='download_batch_qr_pdf'),
    path('orderpiqr/scan-picklist', scan_picklist, name='scan-picklist'), # Keep this outside of i18n to enable POST
    path('orderpiqr/complete-picklist', complete_picklist, name='scan-picklist'), # Keep this outside of i18n to enable POST

    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    path('api/', include('api.urls')),  # your actual API

]

urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    path('', root_redirect, name='root_redirect'),
    path('orderpiqr/', include('orderpiqrApp.urls')),
)

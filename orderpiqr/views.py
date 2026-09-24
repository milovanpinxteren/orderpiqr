from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from orderpiqrApp.utils.devices import (
    get_customer,
    get_fingerprint,
    register_device,
    remember_fingerprint,
    resolve_device,
)
from orderpiqrApp.utils.inventory import is_inventory_enabled, is_orderpicking_enabled
from orderpiqrApp.utils.login_qr import resolve_token
from orderpiqrApp.utils.start_page import resolve_start_page
from django.views.decorators.cache import never_cache
from django.utils.encoding import smart_str
from django.utils.translation import gettext_lazy as _
from django.http import FileResponse, Http404, JsonResponse
from django.conf import settings
from django.contrib.auth.views import PasswordResetView
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from urllib.parse import quote
import os
import threading
import time
import logging
import sys
from django.db.models.functions import TruncDate
from django.db.models import Count
from datetime import date, timedelta
from orderpiqrApp.models import PickList
from django.utils import timezone
from calendar import monthrange

logger = logging.getLogger(__name__)


class CustomPasswordResetView(PasswordResetView):
    template_name = 'registration/password_reset.html'
    email_template_name = 'registration/password_reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'

    def form_valid(self, form):
        email = form.cleaned_data['email']
        users = User.objects.filter(email__iexact=email, is_active=True)
        if not users.exists():
            form.add_error('email', _('No account found with this email address.'))
            return self.form_invalid(form)
        return super().form_valid(form)


def index(request):
    print('index')
    context = {}
    return render(request, 'index.html', context)


def root_redirect(request):
    """Redirect user based on their group after login."""

    # Embedded Shopify admin requests land on the app root (Shopify sets the
    # app URL to the host root); hand them to the Shopify app entry view.
    if request.GET.get('shop', '').endswith('.myshopify.com') and (
            'id_token' in request.GET or 'embedded' in request.GET or 'hmac' in request.GET):
        from integrations_shopify.views import app_entry
        return app_entry(request)

    if not request.user.is_authenticated:
        return redirect('/login/')  # Redirect unauthenticated users to the login page

    if request.user.is_superuser:
        return redirect('/orderpiqr/manage/')  # Redirect superuser to the custom admin
    if request.user.is_staff:
        return redirect('/orderpiqr/manage/')  # Redirect staff to the custom admin
    if request.user.groups.filter(name='companyadmin').exists():
        return redirect('/orderpiqr/manage/')  # Redirect companyadmin to the custom admin
    if request.user.groups.filter(name='orderpicker').exists():
        # Honours the customer's picker_start_page setting, falling back to the
        # enabled features. Shared with the QR login so both land identically.
        try:
            return redirect(resolve_start_page(request.user.userprofile.customer))
        except Exception:
            return redirect('/orderpiqr')  # Fallback on error
    return redirect('/login')  # Redirect to login if no role matches (should not happen)


def custom_login(request):
    is_demo = request.GET.get('demo', 'false') == 'true'
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            device_fingerprint = get_fingerprint(request, request.POST)
            # Pin the fingerprint regardless of whether a device exists yet, so
            # the session fallback works on the very first login too.
            remember_fingerprint(request, device_fingerprint)
            if user.groups.filter(name='orderpicker').exists():
                if resolve_device(request):
                    return redirect('/')  # Redirect to the homepage or desired page
                return redirect('name_entry')  # Redirect to a name entry page
            return redirect('/')  # Redirect to root (or wherever you want after login)
    else:
        if is_demo and settings.DEMO_USER_PASSWORD:
            demo_username = 'orderpicker'
            demo_password = settings.DEMO_USER_PASSWORD
            # Authenticate the demo user automatically
            user = authenticate(request, username=demo_username, password=demo_password)
            if user is not None:
                login(request, user)  # Log the demo user in
                return redirect('name_entry')  # Redirect to the name-entry page

        form = AuthenticationForm()
    return render(request, 'registration/login.html', {'form': form})


# The raw token sits in the URL path, so this page must not hand its own URL to
# third parties in a Referer header. It must NOT be 'no-referrer' though: per
# the Fetch spec ("append a request Origin header"), a page served with
# no-referrer makes the browser send `Origin: null` on its own same-origin form
# POST, and Django's CsrfViewMiddleware rejects that with "Origin checking
# failed - null does not match any trusted origins" — i.e. the Continue button
# 403s. 'same-origin' keeps the token off every other host while leaving our own
# POST's Origin/Referer intact.
QR_LOGIN_REFERRER_POLICY = 'same-origin'


@never_cache
def qr_login(request, token):
    """Redeem a scanned picker login QR.

    GET only renders a confirmation; the session is created on POST. Logging in
    on GET would be a login-CSRF vector — any page could embed the URL as an
    <img> and silently swap the visitor's session for a picker one.

    After login this hands straight back to the normal device flow: a phone
    that has never been registered lands on name entry, a known one goes to the
    picker app — at whichever start page the token or the customer setting
    names.
    """
    login_token = resolve_token(token)

    if login_token is None:
        response = render(request, 'registration/qr_login.html', {'invalid': True}, status=403)
        response['Referrer-Policy'] = QR_LOGIN_REFERRER_POLICY
        return response

    if request.method == 'POST':
        login(request, login_token.user)  # cycles the session key
        login_token.mark_used()
        remember_fingerprint(request, get_fingerprint(request, request.POST))
        destination = resolve_start_page(login_token.customer, login_token.start_page)
        if resolve_device(request):
            return redirect(destination)
        # An unregistered phone names itself first, then carries on to the same
        # destination rather than falling back to the default landing page.
        return redirect(f"{reverse('name_entry')}?next={quote(destination)}")

    response = render(request, 'registration/qr_login.html', {
        'token': login_token,
        'picker': login_token.user,
        'customer': login_token.customer,
        # A shared tablet may already hold someone else's session; warn before
        # we replace it.
        'current_user': request.user if request.user.is_authenticated else None,
    })
    response['Referrer-Policy'] = QR_LOGIN_REFERRER_POLICY
    return response


@login_required
def picker_choice(request):
    """Show choice between order picking and inventory counting."""
    device = resolve_device(request, touch=False)

    # Get customer and check enabled features
    customer = get_customer(request.user)
    orderpicking_enabled = is_orderpicking_enabled(customer)
    inventory_enabled = is_inventory_enabled(customer)

    return render(request, 'registration/picker_choice.html', {
        'device': device,
        'orderpicking_enabled': orderpicking_enabled,
        'inventory_enabled': inventory_enabled,
    })


@login_required
def name_entry(request):
    # Get the 'next' parameter from GET or POST. Validated because it is
    # attacker-supplied: without this, /name-entry/?next=https://evil.example
    # would bounce a freshly logged-in picker off-site.
    next_url = request.POST.get('next') or request.GET.get('next') or '/'
    if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = '/'

    if request.method == 'POST':
        # Handle form submission and save the name to Device model
        name = request.POST.get('name')
        device_fingerprint = get_fingerprint(request, request.POST)

        if name and device_fingerprint:
            # Registers this device for the picker's own customer. The same
            # fingerprint may already exist for another customer — that row is
            # left alone, this one gets its own.
            device, _created = register_device(
                request, name=name, fingerprint=device_fingerprint)
            if device is None:
                messages.error(request, _('Your account is not linked to a customer.'))
            else:
                return redirect(next_url)

    return render(request, 'registration/name_entry.html', {'next': next_url})


@login_required
def download_batch_qr_pdf(request, file_name):
    file_path = os.path.join(settings.MEDIA_ROOT, 'qr_pdfs', file_name)
    if not os.path.exists(file_path):
        raise Http404("Batch QR PDF not found.")

    response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=file_name)
    # Schedule deletion in the background
    delete_file_delayed(file_path)

    return response


def delete_file_delayed(path, delay=10):
    """Delete file after a short delay (in seconds)."""

    def _delete():
        time.sleep(delay)
        try:
            os.remove(path)
        except Exception as e:
            print(f"Failed to delete {path}: {e}")

    threading.Thread(target=_delete).start()

PLAN_LIMIT = 50

def picklists_this_month_cumulative(request):
    customer = getattr(getattr(request.user, "userprofile", None), "customer", None)
    limit_to_customer = bool(customer and not request.user.is_superuser)

    today = timezone.localdate()
    start = today.replace(day=1)
    last_day = monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)

    filters = {"created_at__date__gte": start, "created_at__date__lte": end}
    if limit_to_customer:
        filters["customer"] = customer

    daily = (PickList.objects
             .filter(**filters)
             .annotate(day=TruncDate("created_at"))
             .values("day")
             .annotate(count=Count("pk"))
             .order_by("day"))

    # build day list for the whole month
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    by_day = {row["day"]: row["count"] for row in daily}

    # cumulative
    counts = []
    running = 0
    for d in days:
        running += by_day.get(d, 0)
        counts.append(running)

    return JsonResponse({
        "labels": [d.isoformat() for d in days],
        "counts": counts,
        "limit": PLAN_LIMIT,
        "month_label": today.strftime("%B %Y"),
    })


# Custom error views
def error_400(request, exception=None):
    logger.warning(
        "Bad Request (400) at %s: %s",
        request.path,
        exception,
        extra={'request': request}
    )
    return render(request, '400.html', status=400)


def error_403(request, exception=None):
    logger.warning(
        "Permission Denied (403) at %s: %s | User: %s",
        request.path,
        exception,
        request.user,
        extra={'request': request}
    )
    return render(request, '403.html', status=403)


def error_404(request, exception=None):
    logger.info(
        "Not Found (404): %s",
        request.path,
        extra={'request': request}
    )
    return render(request, '404.html', status=404)


def error_500(request):
    # Get exception info from sys.exc_info()
    exc_info = sys.exc_info()

    # Log the full exception with traceback
    logger.error(
        "Internal Server Error (500) at %s",
        request.path,
        exc_info=exc_info,
        extra={
            'request': request,
            'status_code': 500,
        }
    )

    # Also log request details that might be helpful for debugging
    try:
        logger.error(
            "Request details - Method: %s | User: %s | GET: %s | POST keys: %s",
            request.method,
            getattr(request, 'user', 'Anonymous'),
            dict(request.GET),
            list(request.POST.keys()) if request.POST else [],
        )
    except Exception:
        pass  # Don't let logging errors prevent the error page from showing

    return render(request, '500.html', status=500)

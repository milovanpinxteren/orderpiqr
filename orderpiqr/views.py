from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from orderpiqrApp.models import Device, UserProfile
from django.utils.encoding import smart_str
from django.utils.translation import gettext_lazy as _
from django.http import FileResponse, Http404, JsonResponse
from django.conf import settings
import os
import threading
import time
from django.db.models.functions import TruncDate
from django.db.models import Count
from datetime import date, timedelta
from orderpiqrApp.models import PickList
from django.utils import timezone
from calendar import monthrange


def index(request):
    print('index')
    context = {}
    return render(request, 'index.html', context)


def root_redirect(request):
    """Redirect user based on their group after login."""

    if not request.user.is_authenticated:
        return redirect('/login/')  # Redirect unauthenticated users to the login page

    if request.user.is_superuser:
        return redirect('/admin')  # Redirect superuser to the admin panel
    if request.user.groups.filter(name='companyadmin').exists():
        return redirect('/admin')  # Redirect companyadmin to the admin panel
    if request.user.groups.filter(name='orderpicker').exists():
        return redirect('/orderpiqr')  # Redirect orderpicker to their specific page
    return redirect('/login')  # Redirect to login if no role matches (should not happen)


def custom_login(request):
    is_demo = request.GET.get('demo', 'false') == 'true'
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            device_fingerprint = request.POST.get('device_fingerprint')
            if user.groups.filter(name='orderpicker').exists():
                device = Device.objects.filter(user=request.user, device_fingerprint=device_fingerprint).first()
                if device:
                    device.last_login = datetime.now()
                    device.save()
                    request.session['device_fingerprint'] = device_fingerprint
                    return redirect('/')  # Redirect to the homepage or desired page
                return redirect('name_entry')  # Redirect to a name entry page
            return redirect('/')  # Redirect to root (or wherever you want after login)
    else:
        if is_demo:
            demo_username = 'orderpicker'
            demo_password = 'yfiT328SPfaBaf8'
            # demo_password = 'kerstdiner'
            # Authenticate the demo user automatically
            user = authenticate(request, username=demo_username, password=demo_password)
            if user is not None:
                login(request, user)  # Log the demo user in
                return redirect('name_entry')  # Redirect to the name-entry page

        form = AuthenticationForm()
    return render(request, 'registration/login.html', {'form': form})


def name_entry(request):
    if request.method == 'POST':
        # Handle form submission and save the name to Device model
        name = request.POST.get('name')
        device_fingerprint = request.POST.get('device_fingerprint')

        if name and device_fingerprint:
            user_profile = UserProfile.objects.get(user=request.user)
            customer = user_profile.customer
            if not Device.objects.filter(device_fingerprint=device_fingerprint).exists():
                Device.objects.create(
                    user=request.user,
                    device_fingerprint=device_fingerprint,
                    name=name,
                    description='',
                    customer=customer,
                    last_login=datetime.now(),
                    lists_picked=0
                )
            else:
                print("Device already registered for this user.")
                existing = Device.objects.get(device_fingerprint=device_fingerprint)
                existing.user = request.user
                existing.description = 'Fingerprint used for multiple users'
                existing.last_login = datetime.now()
                existing.save()
            request.session['device_fingerprint'] = device_fingerprint
            return redirect('/')

    return render(request, 'registration/name_entry.html')  # Render a form for name input


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

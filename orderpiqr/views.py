from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm

from orderpiqrApp.models import Device, UserProfile


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
            device = Device.objects.filter(user=request.user, device_fingerprint=device_fingerprint).first()
            if device:
               print('device found, should not happen')
            else:
                Device.objects.create(
                    user=request.user,
                    device_fingerprint=device_fingerprint,
                    name=name,
                    description='',  # You can ask for more details here
                    customer=customer,  # Assign the customer from the UserProfile
                    last_login=datetime.now(),
                    lists_picked=0  # Initialize with 0 or ask for this information
                )
            request.session['device_fingerprint'] = device_fingerprint

            return redirect('/')

    return render(request, 'registration/name_entry.html')  # Render a form for name input

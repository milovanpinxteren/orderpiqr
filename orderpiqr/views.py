from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm

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
            # Authenticate and log the user in
            user = form.get_user()
            login(request, user)
            return redirect('/')  # Redirect to root (or wherever you want after login)
    else:
        form = AuthenticationForm()

    return render(request, 'registration/login.html', {'form': form})
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def company_admin_required(view_func):
    """
    Decorator that requires user to be either:
    - A superuser
    - A staff member
    - A member of the 'companyadmin' group

    Returns 403 Forbidden if the user doesn't meet the criteria.
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        user = request.user
        if user.is_superuser or user.is_staff:
            return view_func(request, *args, **kwargs)
        if user.groups.filter(name='companyadmin').exists():
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("You don't have permission to access this page.")
    return _wrapped_view

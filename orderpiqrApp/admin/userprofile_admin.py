from django.contrib import admin
from orderpiqrApp.models import UserProfile
from django.contrib.auth.models import User


def _user_field_label(name):
    """Reuse auth's own verbose name, which Django already translates."""
    return User._meta.get_field(name).verbose_name


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'customer', 'user_email', 'user_last_login', 'user_is_active')
    search_fields = ['user__username', 'user__email', 'customer__name']
    list_filter = ('customer', 'user__is_active', 'user__groups')
    list_select_related = ('user', 'customer')
    ordering = ('customer__name', 'user__username')

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = _user_field_label('email')
    user_email.admin_order_field = 'user__email'

    def user_last_login(self, obj):
        return obj.user.last_login
    user_last_login.short_description = _user_field_label('last_login')
    user_last_login.admin_order_field = 'user__last_login'

    def user_is_active(self, obj):
        return obj.user.is_active
    user_is_active.short_description = _user_field_label('is_active')
    user_is_active.admin_order_field = 'user__is_active'
    user_is_active.boolean = True

    def get_queryset(self, request):
        """Override queryset to filter by company"""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset  # Superuser can see everything
        if request.user.groups.filter(name='companyadmin').exists():
            # Get the company (customer) associated with the logged-in user
            user_profile = UserProfile.objects.get(user=request.user)
            return queryset.filter(customer=user_profile.customer)  # Only show profiles for the company
        return queryset.none()  # Non-superuser/non-companyadmin users see no profiles

    def save_model(self, request, obj, form, change):
        """Ensure the customer is set for the companyadmin's profile"""
        if not obj.customer:  # If customer is not already set
            if request.user.groups.filter(name='companyadmin').exists():
                user_profile = UserProfile.objects.get(user=request.user)
                obj.customer = user_profile.customer  # Set the customer based on the company of the logged-in admin
        super().save_model(request, obj, form, change)

admin.site.register(UserProfile, UserProfileAdmin)

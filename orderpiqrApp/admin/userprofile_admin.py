from django.contrib import admin
from orderpiqrApp.models import UserProfile, Customer
from django.contrib.auth.models import User

class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'customer', 'get_username')
    search_fields = ['user__username', 'user__email', 'customer__name']
    list_filter = ('customer',)

    def get_username(self, obj):
        return obj.user.username  # Display the username in the admin
    get_username.short_description = 'Username'

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

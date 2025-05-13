from django.contrib import admin
from django.contrib.auth.models import Group

from orderpiqrApp.models import Product, UserProfile


class ProductAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'location', 'customer')  # Display relevant fields
    search_fields = ['code', 'description']

    def get_queryset(self, request):
        """Override queryset to filter by company"""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            user_profile = UserProfile.objects.get(user=request.user)
            return queryset.filter(customer=user_profile.customer)  # Only s # Assuming user is linked to customer
        return queryset.none()


    def save_model(self, request, obj, form, change):
        """Automatically set customer for company admins."""
        if request.user.groups.filter(name='companyadmin').exists():
            user_profile = UserProfile.objects.get(user=request.user)
            obj.customer = user_profile.customer  # Assign the logged-in company's customer
        super().save_model(request, obj, form, change)


    def get_readonly_fields(self, request, obj=None):
        """Make fields like customer read-only for companyadmin"""
        if request.user.groups.filter(name='companyadmin').exists():
            return ['customer']  # Make 'customer' field readonly for companyadmin
        return super().get_readonly_fields(request, obj)

admin.site.register(Product, ProductAdmin)

from django.contrib import admin

from orderpiqrApp.models import Customer, UserProfile


class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ['name', 'description']

    def get_queryset(self, request):
        """Override queryset to filter by user"""
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            user_profile = UserProfile.objects.get(user=request.user)
            return queryset.filter(customer_id=user_profile.customer_id) # Show only companies linked to the current user
        return queryset.none()

admin.site.register(Customer, CustomerAdmin)
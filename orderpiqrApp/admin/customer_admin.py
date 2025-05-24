from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from orderpiqrApp.models import Customer, UserProfile


class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ['name', 'description']

    def customer_link(self, obj):
        """Create a clickable link for the Customer"""
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name), args=[obj.customer_id]),
            obj.name  # This will display the customer's name as the link
        )

    def get_list_display(self, request):
        return super().get_list_display(request) + ('customer_link',)

    # Ensure all columns are clickable
    def get_list_display_links(self, request, list_display):
        return list_display

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
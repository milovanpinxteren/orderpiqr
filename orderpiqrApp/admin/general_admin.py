from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

class GeneralAdmin(admin.ModelAdmin):
    def get_list_display_links(self, request, list_display):
        """Make the entire row clickable"""
        return None  # Make the entire row clickable

    # def get_list_display(self, request):
    #     """Override to ensure that the entire row is clickable"""
    #     return super().get_list_display(request)

    def get_list_display(self, request):
        """Override list_display to ensure the entire row is clickable"""
        # Add a custom method to make all fields clickable
        list_display = super().get_list_display(request)
        return [field if field != 'name' else 'name_link' for field in list_display]
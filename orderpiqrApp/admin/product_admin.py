import openpyxl
from django.contrib import admin
from django.contrib.auth.models import Group
import csv

from django.core.exceptions import ValidationError

from orderpiqrApp.models import Product, UserProfile
from django.contrib import messages
from django import forms

class ProductUploadForm(forms.Form):
    upload_file = forms.FileField()

class ProductAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'location', 'customer')  # Display relevant fields
    search_fields = ['code', 'description']
    # actions = ['upload_file']  # Add the CSV upload action to the admin

    def process_csv_file(self, file, customer):
        """Process CSV file and create products"""
        decoded_file = file.read().decode('utf-8').splitlines()
        csv_reader = csv.reader(decoded_file)
        header = next(csv_reader)  # Skip header row
        header_mapping = {col.strip().lower(): index for index, col in enumerate(header)}

        required_columns = ['code', 'description', 'location']
        for column in required_columns:
            if column not in header_mapping:
                raise ValidationError(f'Missing required column: {column}')
        added = 0
        overwritten = 0
        for row in csv_reader:
            code = row[header_mapping['code']]
            description = row[header_mapping['description']]
            location = int(row[header_mapping['location']])
            product, created = Product.objects.update_or_create(
                code=code,
                customer=customer,
                defaults={'description': description, 'location': location, 'active': True}
            )
            if created:
                added += 1
            else:
                overwritten += 1
        return added, overwritten

    def process_xlsx_file(self, file, customer):
        """Process XLSX file and create products"""
        wb = openpyxl.load_workbook(file)
        sheet = wb.active
        header = [cell.value.lower() for cell in sheet[1]]  # Assuming first row is header

        required_columns = ['code', 'description', 'location']
        for column in required_columns:
            if column not in header:
                raise ValidationError(f'Missing required column: {column}')
        added = 0
        overwritten = 0
        for row in sheet.iter_rows(min_row=2, values_only=True):  # Skip header row
            code, description, location = row[:3]
            product, created = Product.objects.update_or_create(
                code=code,
                customer=customer,
                defaults={'description': description, 'location': int(location), 'active': True}
            )
            if created:
                added += 1
            else:
                overwritten += 1

        return added, overwritten

    def upload_file(self, request, queryset):
        """Handle CSV and XLSX upload"""
        if 'upload_file' in request.FILES:
            file = request.FILES['upload_file']
            try:
                # Get customer for the current user
                user_profile = UserProfile.objects.get(user=request.user)
                customer = user_profile.customer

                # Determine file type
                if file.name.endswith('.csv'):
                    added, overwritten = self.process_csv_file(file, customer)
                elif file.name.endswith('.xlsx'):
                    added, overwritten = self.process_xlsx_file(file, customer)
                else:
                    raise ValidationError("Unsupported file format, only .csv and .xlsx are supported")

                messages.success(request, f'{added} products added, {overwritten} products overwritten.')
            except Exception as e:
                messages.error(request, f'Error processing file: {e}')
        else:
            messages.error(request, 'No file uploaded.')

    upload_file.short_description = 'Upload CSV or XLSX File'

    def changelist_view(self, request, extra_context=None):
        """Override the changelist view to add the file upload form"""
        extra_context = extra_context or {}
        extra_context['product_upload_form'] = ProductUploadForm()
        if request.method == 'POST' and 'upload_file' in request.FILES:
            form = ProductUploadForm(request.POST, request.FILES)
            if form.is_valid():
                # Process the CSV file
                self.upload_file(request, None)  # Call the upload_csv function
            else:
                messages.error(request, 'Invalid form submission.')
        return super().changelist_view(request, extra_context=extra_context)

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
        """Override save_model to handle validation for duplicate codes"""
        if request.user.groups.filter(name='companyadmin').exists():
            user_profile = UserProfile.objects.get(user=request.user)
            obj.customer = user_profile.customer
            if Product.objects.filter(code=obj.code, customer=obj.customer).exists():
                form.add_error(None, f"A product with the code '{obj.code}' already exists for this customer.")
                messages.error(request, f"A product with the code '{obj.code}' already exists, cannot add duplicate.")
                return
            else:
                super().save_model(request, obj, form, change)
                messages.success(request, f"The product '{obj.description}' was added successfully.")

        else:
            raise ValidationError('User is not allowed to save products.')

    def message_user(self, request, message, level=messages.INFO, extra_tags='',
                     fail_silently=False):
        pass

    def get_readonly_fields(self, request, obj=None):
        """Make fields like customer read-only for companyadmin"""
        if request.user.groups.filter(name='companyadmin').exists():
            return ['customer']  # Make 'customer' field readonly for companyadmin
        return super().get_readonly_fields(request, obj)

admin.site.register(Product, ProductAdmin)

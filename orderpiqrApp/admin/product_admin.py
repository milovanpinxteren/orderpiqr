import openpyxl
from django.contrib import admin
import csv
from django.core.exceptions import ValidationError
from orderpiqrApp.models import Product, UserProfile
from django.contrib import messages
from django import forms
from django.utils.translation import gettext_lazy as _
from django.db import transaction


class ProductUploadForm(forms.Form):
    upload_file = forms.FileField()


class ProductAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'location', 'customer')  # Display relevant fields
    search_fields = ['code', 'description']

    # actions = ['upload_file']  # Add the CSV upload action to the admin

    def parse_csv(self, file):
        """Parse CSV and return list of dicts."""
        decoded_file = file.read().decode('utf-8').splitlines()
        csv_reader = csv.reader(decoded_file)
        header = next(csv_reader)
        header_mapping = {col.strip().lower(): index for index, col in enumerate(header)}

        data = []
        for row in csv_reader:
            data.append({
                'code': row[header_mapping['code']],
                'description': row[header_mapping['description']],
                'location': row[header_mapping['location']],
            })
        return data

    def parse_xlsx(self, file):
        """Parse XLSX and return list of dicts."""
        wb = openpyxl.load_workbook(file)
        sheet = wb.active
        header = [str(cell.value).strip().lower() if cell.value else '' for cell in sheet[1]]

        header_mapping = {col: idx for idx, col in enumerate(header)}
        data = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            data.append({
                'code': row[header_mapping['code']],
                'description': row[header_mapping['description']],
                'location': row[header_mapping['location']],
            })
        return data

    def validate_product_data(self, data):
        """Validate product data and return cleaned data or raise ValidationError."""
        required_fields = ['code', 'description', 'location']
        cleaned_data = []

        for idx, item in enumerate(data, start=2):
            for field in required_fields:
                if not item.get(field):
                    raise ValidationError(_('Missing value for "%(field)s" in row %(row)d') % {
                        'field': field,
                        'row': idx,
                    })
            try:
                item['location'] = int(item['location'])
            except ValueError:
                raise ValidationError(_('Invalid number for "location" in row %(row)d') % {
                    'row': idx,
                })
            cleaned_data.append(item)
        return cleaned_data

    from django.db import transaction

    def add_products(self, cleaned_data, customer):
        """Bulk add or update products"""
        added = 0
        overwritten = 0
        existing_products = Product.objects.filter(
            customer=customer,
            code__in=[item['code'] for item in cleaned_data]
        )
        existing_map = {p.code: p for p in existing_products}
        to_create = []
        to_update = []

        for item in cleaned_data:
            code = item['code']
            if code in existing_map:
                product = existing_map[code]
                product.description = item['description']
                product.location = item['location']
                product.active = True
                to_update.append(product)
            else:
                to_create.append(Product(
                    code=code,
                    description=item['description'],
                    location=item['location'],
                    customer=customer,
                    active=True,
                ))

        with transaction.atomic():
            if to_create:
                Product.objects.bulk_create(to_create)
            if to_update:
                Product.objects.bulk_update(to_update, ['description', 'location', 'active'])

        added = len(to_create)
        overwritten = len(to_update)
        return added, overwritten

    def process_csv_file(self, file, customer):
        data = self.parse_csv(file)
        cleaned_data = self.validate_product_data(data)
        return self.add_products(cleaned_data, customer)

    def process_xlsx_file(self, file, customer):
        data = self.parse_xlsx(file)
        cleaned_data = self.validate_product_data(data)
        return self.add_products(cleaned_data, customer)

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
                    raise ValidationError(_('Unsupported file format, only .csv and .xlsx are supported'))

                messages.success(request, _('%(added)d products added, %(overwritten)d products overwritten.') % {
                    'added': added,
                    'overwritten': overwritten,
                })

            except Exception as e:
                messages.error(request, _('Error processing file: %(error)s') % {
                    'error': e, })
        else:
            messages.error(request, _('No file uploaded.'))

    upload_file.short_description = _('Upload CSV or XLSX File')

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
                messages.error(request, _('Invalid form submission.'))
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
                form.add_error(None, _('A product with the code "%(code)s" already exists for this customer.') % {
                    'code': obj.code,
                })
                messages.error(request,
                               _('A product with the code "%(code)s" already exists, cannot add duplicate.') % {
                                   'code': obj.code,
                               })
                return
            else:
                super().save_model(request, obj, form, change)
                messages.success(request, _('The product "%(description)s" was added successfully.') % {
                    'description': obj.description,
                })

        else:
            raise ValidationError(_('User is not allowed to save products.'))

    def message_user(self, request, message, level=messages.INFO, extra_tags='',
                     fail_silently=False):
        pass

    def get_readonly_fields(self, request, obj=None):
        """Make fields like customer read-only for companyadmin"""
        if request.user.groups.filter(name='companyadmin').exists():
            return ['customer']  # Make 'customer' field readonly for companyadmin
        return super().get_readonly_fields(request, obj)


admin.site.register(Product, ProductAdmin)

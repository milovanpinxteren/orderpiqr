import openpyxl
import csv
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django import forms
from orderpiqrApp.models import Order, OrderLine, Product, UserProfile, PickList, ProductPick
from django.utils.translation import gettext_lazy as _
from orderpiqrApp.utils.qr_pdf_generator import QRPDFGenerator  # You’ll build this next
from django.shortcuts import redirect
from django.urls import reverse

class OrderUploadForm(forms.Form):
    upload_file = forms.FileField()



class OrderAdmin(admin.ModelAdmin):
    class OrderLineInline(admin.TabularInline):  # or admin.StackedInline
        model = OrderLine
        extra = 0
        readonly_fields = ('__str__',)
        fields = ('__str__',)

        can_delete = False
        show_change_link = False

    @admin.action(description=_("Generate QR PDF for selected Orders"))
    def generate_qr_codes(self, request, queryset):
        if not queryset.exists():
            self.message_user(request, _("No orders selected."), level=messages.WARNING)
            return

        try:
            generator = QRPDFGenerator()
            pdf_path = generator.generate_multiple(queryset)
            return redirect(reverse('download_batch_qr_pdf'))  # See next step

        except Exception as e:
            self.message_user(request, _("Failed to generate QR batch: %(error)s") % {"error": e}, level=messages.ERROR)

    list_display = ('order_code', 'customer', 'created_at')
    search_fields = ['order_code']
    inlines = [OrderLineInline]
    actions = [generate_qr_codes]

    def parse_rows(self, rows, header_mapping, customer):
        overwritten_orders = set()
        orders_created = 0
        lines_added = 0
        order_map = {}

        for row in rows:
            if all(cell is None for cell in row) or not row or all(str(cell).strip() == '' for cell in row):
                break  # Treat fully empty row (e.g. ['', '', '']) as end of file

            order_code = str(row[header_mapping['order_code']]).strip()
            product_code = str(row[header_mapping['product_code']]).strip()
            quantity = row[header_mapping['quantity']]

            if not order_code:
                raise ValidationError(_("A row is missing an order code. Please ensure all rows have valid data."))

            try:
                quantity = int(quantity)
            except ValueError:
                raise ValidationError(_("Invalid quantity value for product code '%(code)s'. Must be a number.") % {
                    "code": product_code
                })

            try:
                product = Product.objects.get(code=product_code, customer=customer)
            except Product.DoesNotExist:
                raise ValidationError(_("Unknown product code '%(code)s'. Please check your file.") % {
                    "code": product_code
                })

            if order_code not in order_map:
                order_obj, created = Order.objects.get_or_create(order_code=order_code, customer=customer)
                order_map[order_code] = order_obj
                orders_created += 1
                if not created:
                    OrderLine.objects.filter(order=order_obj).delete()
                    overwritten_orders.add(order_code)
            else:
                order_obj = order_map[order_code]

            OrderLine.objects.create(order=order_obj, product=product, quantity=quantity)
            lines_added += 1

        return orders_created, lines_added, overwritten_orders

    def process_csv_file(self, file, customer):
        decoded_file = file.read().decode('utf-8').splitlines()
        csv_reader = csv.reader(decoded_file)
        header = next(csv_reader)
        header_mapping = {col.strip().lower(): index for index, col in enumerate(header)}

        required_columns = ['order_code', 'product_code', 'quantity']
        for column in required_columns:
            if column not in header_mapping:
                raise ValidationError(f'Missing required column: {column}')

        return self.parse_rows(csv_reader, header_mapping, customer)

    def process_xlsx_file(self, file, customer):
        wb = openpyxl.load_workbook(file)
        sheet = wb.active
        header = [cell.value.lower() for cell in sheet[1]]

        required_columns = ['order_code', 'product_code', 'quantity']
        for column in required_columns:
            if column not in header:
                raise ValidationError(f'Missing required column: {column}')

        header_mapping = {col: index for index, col in enumerate(header)}
        rows = list(sheet.iter_rows(min_row=2, values_only=True))

        return self.parse_rows(rows, header_mapping, customer)

    def upload_file(self, request, queryset):
        if 'upload_file' in request.FILES:
            file = request.FILES['upload_file']
            try:
                user_profile = UserProfile.objects.get(user=request.user)
                customer = user_profile.customer

                if file.name.endswith('.csv'):
                    orders_created, lines_added, overwritten_orders = self.process_csv_file(file, customer)
                elif file.name.endswith('.xlsx'):
                    orders_created, lines_added, overwritten_orders = self.process_xlsx_file(file, customer)
                else:
                    raise ValidationError("Unsupported file format, only .csv and .xlsx are supported")

                msg = _("%(orders)s orders and %(lines)s lines added.") % {
                    "orders": orders_created,
                    "lines": lines_added
                }

                if overwritten_orders:
                    overwritten_list = ", ".join(sorted(str(code) for code in overwritten_orders))
                    msg += " " + _("Overwritten orders: %(codes)s.") % {"codes": overwritten_list}

                messages.success(request, msg)

            except Exception as e:
                error_message = str(e)
                if isinstance(e, ValidationError) and hasattr(e, 'messages'):
                    error_message = e.messages[0]
                messages.error(request, _("Error processing file: %(msg)s") % {"msg": error_message})
        else:
            messages.error(request, 'No file uploaded.')

    upload_file.short_description = 'Upload CSV or XLSX File'

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['order_upload_form'] = OrderUploadForm()
        if request.method == 'POST' and 'upload_file' in request.FILES:
            form = OrderUploadForm(request.POST, request.FILES)
            if form.is_valid():
                self.upload_file(request, None)
            else:
                messages.error(request, 'Invalid form submission.')
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if request.user.groups.filter(name='companyadmin').exists():
            user_profile = UserProfile.objects.get(user=request.user)
            return queryset.filter(customer=user_profile.customer)
        return queryset.none()

    def get_readonly_fields(self, request, obj=None):
        if request.user.groups.filter(name='companyadmin').exists():
            return ['customer']
        return super().get_readonly_fields(request, obj)



admin.site.register(Order, OrderAdmin)
admin.site.register(OrderLine)

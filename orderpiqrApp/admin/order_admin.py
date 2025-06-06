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
from django.db import transaction


class OrderUploadForm(forms.Form):
    upload_file = forms.FileField()


class OrderAdmin(admin.ModelAdmin):
    class OrderLineInline(admin.TabularInline):  # or admin.StackedInline
        model = OrderLine
        extra = 1
        # readonly_fields = ('__str__',)
        # fields = ('__str__',)

        can_delete = False
        show_change_link = False

    @admin.action(description=_("Generate QR PDF for selected Orders"))
    def generate_qr_codes(self, request, queryset):
        if not queryset.exists():
            self.message_user(request, _("No orders selected."), level=messages.WARNING)
            return

        try:
            generator = QRPDFGenerator()
            filename = generator.generate_multiple(queryset)
            return redirect(reverse('download_batch_qr_pdf', args=[filename]))

        except Exception as e:
            self.message_user(request, _("Failed to generate QR batch: %(error)s") % {"error": e}, level=messages.ERROR)

    list_display = ('order_code', 'customer', 'created_at')
    search_fields = ['order_code']
    inlines = [OrderLineInline]
    actions = [generate_qr_codes]

    def parse_csv(self, file):
        decoded_file = file.read().decode('utf-8').splitlines()
        csv_reader = csv.reader(decoded_file)
        header = next(csv_reader)
        header_mapping = {col.strip().lower(): index for index, col in enumerate(header)}

        rows = list(csv_reader)
        return header_mapping, rows

    def parse_xlsx(self, file):
        wb = openpyxl.load_workbook(file)
        sheet = wb.active
        header = [str(cell.value).strip().lower() if cell.value else '' for cell in sheet[1]]
        header_mapping = {col: index for index, col in enumerate(header)}
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        return header_mapping, rows

    def validate_order_data(self, rows, header_mapping, customer):
        required_columns = ['order_code', 'product_code', 'quantity']
        for column in required_columns:
            if column not in header_mapping:
                raise ValidationError(_('Missing required column: "%(column)s"') % {'column': column})

        cleaned_rows = []
        errors = []
        product_queryset = Product.objects.filter(customer=customer)
        product_map = {product.code: product for product in product_queryset}

        for idx, row in enumerate(rows, start=2):
            if not row or all(cell is None or str(cell).strip() == '' for cell in row):
                break  # Empty row = end of file

            order_code = str(row[header_mapping['order_code']]).strip()
            product_code = str(row[header_mapping['product_code']]).strip()
            quantity = row[header_mapping['quantity']]

            if not order_code:
                errors.append(_('Missing value for "order_code" in row %(row)d') % {'row': idx})
                continue

            try:
                quantity = int(quantity)
            except (ValueError, TypeError):
                raise ValidationError(_('Invalid quantity for product code "%(code)s" in row %(row)d') % {
                    'code': product_code,
                    'row': idx
                })

            product = product_map.get(product_code)
            if not product:
                errors.append(_('Unknown product code "%(code)s" in row %(row)d') % {
                    'code': product_code, 'row': idx})
                continue

            cleaned_rows.append({
                'order_code': order_code,
                'product': product,
                'quantity': quantity,
            })

        if errors:
            raise ValidationError(errors[0])

        return cleaned_rows


    def add_orders(self, cleaned_rows, customer):
        order_map = {}
        lines_to_create = []
        orders_created = 0
        lines_added = 0
        overwritten_orders = set()

        with transaction.atomic():
            for item in cleaned_rows:
                order_code = item['order_code']
                product = item['product']
                quantity = item['quantity']

                if order_code not in order_map:
                    order_obj, created = Order.objects.get_or_create(
                        order_code=order_code,
                        customer=customer
                    )
                    order_map[order_code] = order_obj
                    if created:
                        orders_created += 1
                    else:
                        OrderLine.objects.filter(order=order_obj).delete()
                        overwritten_orders.add(order_code)
                else:
                    order_obj = order_map[order_code]

                lines_to_create.append(OrderLine(
                    order=order_obj,
                    product=product,
                    quantity=quantity,
                ))
                lines_added += 1

            OrderLine.objects.bulk_create(lines_to_create)

        return orders_created, lines_added, overwritten_orders

    def process_csv_file(self, file, customer):
        header_mapping, rows = self.parse_csv(file)
        cleaned_rows = self.validate_order_data(rows, header_mapping, customer)
        return self.add_orders(cleaned_rows, customer)

    def process_xlsx_file(self, file, customer):
        header_mapping, rows = self.parse_xlsx(file)
        cleaned_rows = self.validate_order_data(rows, header_mapping, customer)
        return self.add_orders(cleaned_rows, customer)

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

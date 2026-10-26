"""
Custom Admin Management Views

A user-friendly custom admin interface for company administrators.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum, Max
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _, ngettext
from collections import Counter
from datetime import timedelta
import json
import csv
import io

from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.hashers import check_password

from orderpiqrApp.utils.decorators import company_admin_required
from orderpiqrApp.utils.csv_import import (
    CSVImportError, read_csv_rows, parse_bool, PRODUCT_CSV_FIELDS, ORDER_CSV_FIELDS,
)
from orderpiqrApp.utils.build_id import get_build_id
from orderpiqrApp.utils.health import health_window, pick_outcomes
from orderpiqrApp.utils.inventory import is_inventory_enabled, is_queue_enabled, modify_inventory
from orderpiqrApp.utils.login_qr import active_token, issue_token, login_url
from orderpiqrApp.utils.products import code_conflict, merge_products, resolve_product, set_alias_codes, set_primary_code
from orderpiqrApp.utils.start_page import QUEUE, SCAN, TOKEN_START_PAGE_CHOICES
from orderpiqrApp.models import Product, ProductBarcode, Order, OrderLine, PickList, ProductPick, Device, CustomerSettingValue, SettingDefinition, InventoryLog, ScanEvent, resolve_pending_picks_to_lost
from django.contrib.auth.models import User


def get_customer_from_user(user):
    """Get the customer associated with the user."""
    if hasattr(user, 'userprofile') and user.userprofile.customer:
        return user.userprofile.customer
    return None


def get_base_context(request, active_nav='dashboard'):
    """Get the base context for all manage views."""
    customer = get_customer_from_user(request.user)
    inventory_enabled = is_inventory_enabled(customer) if customer else False
    return {
        'user': request.user,
        'customer': customer,
        'active_nav': active_nav,
        'inventory_enabled': inventory_enabled,
        'queue_enabled': is_queue_enabled(customer) if customer else False,
    }


def _querystring_without_page(request):
    """Current GET params minus `page`, for pagination links that must keep
    every active filter."""
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


# ============================================
# Dashboard
# ============================================

@company_admin_required
def dashboard(request):
    """Main dashboard with key metrics and quick actions."""
    context = get_base_context(request, 'dashboard')
    customer = context['customer']

    if not customer:
        messages.error(request, _("No customer profile found for your account."))
        return redirect('login')

    # Get today and date ranges
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Product stats
    products = Product.objects.filter(customer=customer)
    context['total_products'] = products.count()
    context['active_products'] = products.filter(active=True).count()

    # Order stats
    orders = Order.objects.filter(customer=customer)
    context['total_orders'] = orders.count()
    context['orders_today'] = orders.filter(created_at__date=today).count()
    context['orders_this_week'] = orders.filter(created_at__date__gte=week_ago).count()

    # Queue stats
    context['orders_in_queue'] = orders.filter(status__in=['queued', 'in_progress']).count()
    context['orders_draft'] = orders.filter(status='draft').count()
    context['orders_completed_today'] = orders.filter(
        status='completed',
        completed_at__date=today
    ).count()

    # Picklist stats
    picklists = PickList.objects.filter(customer=customer)
    context['active_picklists'] = picklists.filter(pick_started=True, successful__isnull=True).count()
    context['completed_picklists_today'] = picklists.filter(
        successful=True,
        pick_time__date=today
    ).count()

    # Device stats
    devices = Device.objects.filter(customer=customer)
    context['total_devices'] = devices.count()
    context['active_devices'] = devices.filter(
        last_login__gte=timezone.now() - timedelta(minutes=15)
    ).count()

    # Pick-flow health
    now = timezone.now()
    scan_events = ScanEvent.objects.filter(customer=customer)
    scan_issues = scan_events.exclude(event_type='manual_override')
    context['scan_issues_7d'] = scan_issues.filter(created_at__gte=now - timedelta(days=7)).count()
    context['scan_issues_24h'] = scan_issues.filter(created_at__gte=now - timedelta(hours=24)).count()
    context['manual_overrides_7d'] = scan_events.filter(
        event_type='manual_override',
        created_at__gte=now - timedelta(days=7)
    ).count()
    context['recent_scan_events'] = scan_events.select_related('device').order_by('-created_at')[:8]

    # Picklists stuck in progress: started over 4 hours ago and never finished.
    stale_picklists = picklists.filter(
        pick_started=True,
        successful__isnull=True,
        archived=False,
        pick_time__lt=now - timedelta(hours=4)
    ).order_by('pick_time')
    context['stale_picklists_count'] = stale_picklists.count()
    context['stale_picklists'] = stale_picklists[:5]

    # Recent orders (last 5)
    context['recent_orders'] = orders.select_related().order_by('-created_at')[:5]

    # Recent completions
    context['recent_completions'] = orders.filter(
        status='completed'
    ).order_by('-completed_at')[:5]

    # Chart data - orders per day (last 7 days)
    chart_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = orders.filter(created_at__date=day).count()
        chart_data.append({
            'date': day.strftime('%a'),
            'count': count
        })
    context['chart_data'] = json.dumps(chart_data)

    return render(request, 'manage/dashboard.html', context)


# ============================================
# Products
# ============================================

def _parse_barcode_input(raw):
    """Split the form's barcodes field (newline- or comma-separated) into a
    deduplicated list of codes."""
    codes = []
    for chunk in (raw or '').replace(',', '\n').splitlines():
        code = chunk.strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def _barcode_errors(customer, primary_code, barcodes, exclude_product=None):
    """Validate alias codes against the primary and other products' codes."""
    errors = []
    for code in barcodes:
        if code == primary_code:
            errors.append(_("Barcode '{code}' is the same as the product code.").format(code=code))
        elif code_conflict(customer, code, exclude_product=exclude_product):
            errors.append(_("Barcode '{code}' is already in use by another product.").format(code=code))
    return errors

def _filtered_products(customer, params):
    """Product queryset for the given filter params (search/status/location).
    Shared by the list view and the bulk endpoint's select-all mode so that
    "select everything matching this filter" means exactly what the list shows."""
    products = Product.objects.filter(customer=customer)
    search = (params.get('search') or '').strip()
    if search:
        products = products.filter(
            Q(code__icontains=search) |
            Q(barcodes__code__icontains=search) |
            Q(description__icontains=search) |
            Q(location__icontains=search)
        ).distinct()
    status = params.get('status') or ''
    if status == 'active':
        products = products.filter(active=True)
    elif status == 'inactive':
        products = products.filter(active=False)
    location = params.get('location') or ''
    if location:
        products = products.filter(location=location)
    return products


@company_admin_required
def products_list(request):
    """List all products with search and filter."""
    context = get_base_context(request, 'products')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    products = _filtered_products(customer, request.GET)
    context['search'] = request.GET.get('search', '').strip()
    context['status_filter'] = request.GET.get('status', '')
    context['location_filter'] = request.GET.get('location', '')

    # Get distinct locations for the filter dropdown
    context['locations'] = list(
        Product.objects.filter(customer=customer, location__gt='')
        .values_list('location', flat=True).distinct().order_by('location')
    )

    # Ordering
    ordering = request.GET.get('order', 'code')
    if ordering in ['code', '-code', 'description', '-description', 'location', '-location', 'product_id', '-product_id']:
        products = products.order_by(ordering)
    context['ordering'] = ordering

    # Add order count annotation
    products = products.annotate(order_count=Count('orderline'))

    # Pagination
    paginator = Paginator(products, 25)
    page = request.GET.get('page', 1)
    context['products'] = paginator.get_page(page)
    context['paginator'] = paginator
    context['querystring'] = _querystring_without_page(request)

    return render(request, 'manage/products/list.html', context)


@company_admin_required
def product_create(request):
    """Create a new product."""
    context = get_base_context(request, 'products')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        location = request.POST.get('location', '').strip()
        active = request.POST.get('active') == 'on'
        barcodes = _parse_barcode_input(request.POST.get('barcodes', ''))

        errors = []
        if not code:
            errors.append(_("Product code is required."))
        elif code_conflict(customer, code):
            errors.append(_("A product with this code already exists."))
        if not description:
            errors.append(_("Description is required."))
        errors.extend(_barcode_errors(customer, code, barcodes))

        if errors:
            for error in errors:
                messages.error(request, error)
            context['form_data'] = request.POST
            return render(request, 'manage/products/form.html', context)

        product = Product.objects.create(
            customer=customer,
            code=code,
            description=description,
            location=location,
            active=active
        )
        set_alias_codes(product, barcodes)
        messages.success(request, _("Product '{code}' created successfully.").format(code=code))
        return redirect('manage_products')

    context['is_create'] = True

    # Prefill from ?code=... (e.g. "Add as product" on the health page).
    # Reuses the template's form_data re-render path; 'active' mirrors the
    # checked-by-default state of a fresh form.
    prefill_code = request.GET.get('code', '').strip()
    if prefill_code:
        context['form_data'] = {'code': prefill_code, 'active': 'on'}

    return render(request, 'manage/products/form.html', context)


@company_admin_required
def product_edit(request, product_id):
    """Edit an existing product."""
    context = get_base_context(request, 'products')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    product = get_object_or_404(Product, product_id=product_id, customer=customer)
    context['product'] = product

    # Add inventory data if enabled
    if context.get('inventory_enabled'):
        context['inventory_logs'] = InventoryLog.objects.filter(
            product=product,
            deleted=False
        ).select_related('user', 'device').order_by('-created_at')[:10]
        context['inventory_reasons'] = InventoryLog.Reason.choices

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        location = request.POST.get('location', '').strip()
        active = request.POST.get('active') == 'on'
        barcodes = _parse_barcode_input(request.POST.get('barcodes', ''))

        errors = []
        if not code:
            errors.append(_("Product code is required."))
        elif code_conflict(customer, code, exclude_product=product):
            errors.append(_("A product with this code already exists."))
        if not description:
            errors.append(_("Description is required."))
        errors.extend(_barcode_errors(customer, code, barcodes, exclude_product=product))

        if errors:
            for error in errors:
                messages.error(request, error)
            context['form_data'] = request.POST
            return render(request, 'manage/products/form.html', context)

        product.code = code
        product.description = description
        product.location = location
        product.active = active
        product.save()
        # The form is the explicit desired state of every code — no automatic
        # demotion of the old primary here (unlike the sync API): the admin
        # lists the barcodes they want to keep.
        set_alias_codes(product, barcodes)

        messages.success(request, _("Product '{code}' updated successfully.").format(code=code))
        return redirect('manage_products')

    context['is_create'] = False
    return render(request, 'manage/products/form.html', context)


@company_admin_required
def product_delete(request, product_id):
    """Delete a product (AJAX)."""
    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    product = get_object_or_404(Product, product_id=product_id, customer=customer)

    if request.method == 'POST':
        code = product.code
        product.delete()
        return JsonResponse({'status': 'ok', 'message': _("Product '{code}' deleted.").format(code=code)})

    return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)


@company_admin_required
def products_bulk_action(request):
    """Handle bulk actions on products (AJAX)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)

    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': _("Invalid request.")}, status=400)

    action = data.get('action', '')

    if data.get('select_all'):
        # "Select all matching" mode: operate on everything matching the
        # list's current filters instead of an explicit id list.
        products = _filtered_products(customer, data.get('filters') or {})
    else:
        product_ids = data.get('product_ids', [])
        if not product_ids:
            return JsonResponse({'status': 'error', 'message': _("No products selected.")}, status=400)
        products = Product.objects.filter(customer=customer, product_id__in=product_ids)
    count = products.count()
    if not count:
        return JsonResponse({'status': 'error', 'message': _("No products selected.")}, status=400)

    if action == 'delete':
        # OrderLine.product is on_delete=PROTECT: products referenced by an
        # order can't be deleted, so skip them instead of failing the batch.
        deletable = products.annotate(line_count=Count('orderline')).filter(line_count=0)
        deleted = deletable.count()
        skipped = count - deleted
        deletable.delete()
        message = ngettext(
            "%(count)s product deleted.",
            "%(count)s products deleted.",
            deleted) % {'count': deleted}
        if skipped:
            message += " " + ngettext(
                "%(count)s product skipped because it is used in orders.",
                "%(count)s products skipped because they are used in orders.",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})
    elif action == 'activate':
        products.update(active=True)
        return JsonResponse({'status': 'ok', 'message': ngettext(
            "%(count)s product activated.",
            "%(count)s products activated.",
            count) % {'count': count}})
    elif action == 'deactivate':
        products.update(active=False)
        return JsonResponse({'status': 'ok', 'message': ngettext(
            "%(count)s product deactivated.",
            "%(count)s products deactivated.",
            count) % {'count': count}})
    elif action == 'set_location':
        new_location = data.get('value', '').strip()
        products.update(location=new_location)
        return JsonResponse({'status': 'ok', 'message': ngettext(
            "%(count)s product updated.",
            "%(count)s products updated.",
            count) % {'count': count}})
    elif action == 'merge':
        # Merge the selected products into the one identified by `value`
        # (its product code). Their codes stay scannable as barcode aliases.
        target_code = str(data.get('value') or '').strip()
        if not target_code:
            return JsonResponse({'status': 'error', 'message': _("Enter the product code to merge into.")}, status=400)
        # Aliases are accepted too: any scannable code identifies the target.
        target = resolve_product(customer, target_code)
        if target is None:
            return JsonResponse({'status': 'error', 'message': _("No product with code '{code}' found.").format(code=target_code)}, status=400)
        sources = list(products.exclude(product_id=target.product_id))
        if not sources:
            return JsonResponse({'status': 'error', 'message': _("Select at least one other product to merge.")}, status=400)
        # One transaction for the whole batch: a failure mid-loop must not
        # leave half the selection merged.
        with transaction.atomic():
            for source in sources:
                merge_products(target, source, user=request.user)
        return JsonResponse({'status': 'ok', 'message': ngettext(
            "%(count)s product merged into '%(code)s'. Its code remains scannable as a barcode.",
            "%(count)s products merged into '%(code)s'. Their codes remain scannable as barcodes.",
            len(sources)) % {'count': len(sources), 'code': target.code}})
    else:
        return JsonResponse({'status': 'error', 'message': _("Unknown action.")}, status=400)


@company_admin_required
def product_inline_edit(request, product_id):
    """Inline edit a single product field (AJAX)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)

    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    product = get_object_or_404(Product, product_id=product_id, customer=customer)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': _("Invalid request.")}, status=400)

    field = data.get('field', '')
    value = data.get('value', '')

    allowed_fields = ['code', 'description', 'location', 'active', 'inventory_quantity']
    if field not in allowed_fields:
        return JsonResponse({'status': 'error', 'message': _("Invalid field.")}, status=400)

    # Handle inventory_quantity field specially (create log entry)
    if field == 'inventory_quantity':
        if not is_inventory_enabled(customer):
            return JsonResponse({'status': 'error', 'message': _("Inventory management is not enabled.")}, status=403)
        try:
            value = int(value)
            if value < 0:
                return JsonResponse({'status': 'error', 'message': _("Quantity cannot be negative.")}, status=400)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': _("Invalid quantity value.")}, status=400)

        # Create log entry for admin correction
        modify_inventory(
            product=product,
            user=request.user,
            change_type=InventoryLog.ChangeType.SET,
            reason=InventoryLog.Reason.CORRECTION,
            value=value,
            notes=_("Inline edit from admin panel")
        )
        return JsonResponse({'status': 'ok', 'message': _("Inventory updated.")})

    if field == 'active':
        value = value in [True, 'true', '1']
    elif field in ['code', 'description']:
        value = value.strip()
        if not value:
            return JsonResponse({'status': 'error', 'message': _("This field cannot be empty.")}, status=400)
        if field == 'code' and code_conflict(customer, value, exclude_product=product):
            return JsonResponse({'status': 'error', 'message': _("A product with this code already exists.")}, status=400)

    if field == 'code':
        # Same contract as the sync API: the old primary stays scannable as an
        # extra barcode ("never forget a code"). The full edit form is the
        # explicit desired state of every code and does not do this.
        changed = value != product.code
        set_primary_code(product, value)
        message = (_("Updated. The previous code remains scannable as an extra barcode.")
                   if changed else _("Updated."))
        return JsonResponse({'status': 'ok', 'message': message})

    setattr(product, field, value)
    product.save(update_fields=[field])

    return JsonResponse({'status': 'ok', 'message': _("Updated.")})


@company_admin_required
def products_import(request):
    """Import products from CSV."""
    context = get_base_context(request, 'products')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, _("Please select a CSV file."))
            return render(request, 'manage/products/import.html', context)

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, _("Please upload a valid CSV file."))
            return render(request, 'manage/products/import.html', context)

        try:
            rows = read_csv_rows(csv_file, PRODUCT_CSV_FIELDS)

            created_count = 0
            updated_count = 0
            skipped_rows = []

            # Resolve barcode aliases too: a row carrying a superseded EAN must
            # update the existing product, not create a duplicate. Two queries
            # up front instead of one per row; primary codes win over aliases.
            csv_codes = [row['code'][:255] for _line, row in rows]
            existing_by_code = {}
            for barcode in ProductBarcode.objects.filter(
                    customer=customer, code__in=csv_codes).select_related('product'):
                existing_by_code[barcode.code] = barcode.product
            for product in Product.objects.filter(customer=customer, code__in=csv_codes):
                existing_by_code[product.code] = product

            for line_number, row in rows:
                code = row['code'][:255]
                description = row['description']
                location = row['location'][:50]
                active = parse_bool(row['active'])

                if not code or not description:
                    skipped_rows.append(line_number)
                    continue

                product = existing_by_code.get(code)
                if product is None:
                    # Register the creation so a duplicate row later in the
                    # file updates it instead of creating a second product.
                    existing_by_code[code] = Product.objects.create(
                        customer=customer,
                        code=code,
                        description=description,
                        location=location,
                        active=active,
                    )
                    created_count += 1
                else:
                    product.description = description
                    product.location = location
                    product.active = active
                    product.save(update_fields=['description', 'location', 'active'])
                    updated_count += 1

            if not created_count and not updated_count:
                messages.error(request, _(
                    "No products were imported: every row is missing a product code or description. "
                    "Please check the CSV format below."
                ))
                return render(request, 'manage/products/import.html', context)

            messages.success(request, _("Import completed: {created} created, {updated} updated.").format(
                created=created_count, updated=updated_count
            ))
            if skipped_rows:
                messages.warning(request, ngettext(
                    "%(count)s row was skipped because the product code or description was empty (row: %(rows)s).",
                    "%(count)s rows were skipped because the product code or description was empty (rows: %(rows)s).",
                    len(skipped_rows)) % {
                        'count': len(skipped_rows),
                        # The count is the true total but the list is capped,
                        # so mark the truncation: "50 rows were skipped (rows:
                        # 2, 3, ... 11)" otherwise reads as the complete list.
                        'rows': ', '.join(str(r) for r in skipped_rows[:10])
                                + (', …' if len(skipped_rows) > 10 else ''),
                    })
            return redirect('manage_products')

        except CSVImportError as e:
            messages.error(request, str(e))
            return render(request, 'manage/products/import.html', context)
        except Exception as e:
            messages.error(request, _("Error processing CSV: {error}").format(error=str(e)))
            return render(request, 'manage/products/import.html', context)

    return render(request, 'manage/products/import.html', context)


@company_admin_required
def products_export(request):
    """Export products to CSV."""
    customer = get_customer_from_user(request.user)
    if not customer:
        return redirect('manage_dashboard')

    products = Product.objects.filter(customer=customer).order_by('code')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="products.csv"'

    writer = csv.writer(response)
    writer.writerow(['code', 'description', 'location', 'active'])

    for product in products:
        writer.writerow([
            product.code,
            product.description,
            product.location,
            'true' if product.active else 'false'
        ])

    return response


# ============================================
# Orders
# ============================================

def _filtered_orders(customer, params):
    """Order queryset for the given filter params (search/status/source/date
    range). Shared by the list view and the bulk endpoint's select-all mode so
    that "select everything matching this filter" means exactly what the list
    shows."""
    orders = Order.objects.filter(customer=customer)
    search = (params.get('search') or '').strip()
    if search:
        orders = orders.filter(
            Q(order_code__icontains=search) |
            Q(notes__icontains=search)
        )
    status = params.get('status') or ''
    if status in ['draft', 'queued', 'in_progress', 'completed', 'cancelled']:
        orders = orders.filter(status=status)
    source = params.get('source') or ''
    if source:
        orders = orders.filter(source=source)
    date_from = parse_date(params.get('date_from') or '')
    if date_from:
        orders = orders.filter(created_at__date__gte=date_from)
    date_to = parse_date(params.get('date_to') or '')
    if date_to:
        orders = orders.filter(created_at__date__lte=date_to)
    return orders


def _filtered_picklists(customer, params):
    """PickList queryset for the given filter params (status, code, device, date
    range). Shared by the list view and the bulk endpoint's select-all mode so
    that "select everything matching this filter" means exactly what the list
    shows."""
    picklists = PickList.objects.filter(customer=customer).select_related('device', 'order')
    status = params.get('status') or ''
    if status == 'pending':
        picklists = picklists.filter(pick_started__isnull=True)
    elif status == 'in_progress':
        picklists = picklists.filter(pick_started=True, successful__isnull=True, archived=False)
    elif status == 'completed':
        picklists = picklists.filter(successful=True)
    elif status == 'failed':
        picklists = picklists.filter(successful=False)
    elif status == 'archived':
        picklists = picklists.filter(archived=True)
    search = (params.get('q') or '').strip()
    if search:
        picklists = picklists.filter(picklist_code__icontains=search)
    device_id = params.get('device') or ''
    if device_id:
        try:
            device_id = int(device_id)
            picklists = picklists.filter(device_id=device_id)
        except (ValueError, TypeError):
            pass
    date_from = parse_date(params.get('date_from') or '')
    if date_from:
        picklists = picklists.filter(created_at__date__gte=date_from)
    date_to = parse_date(params.get('date_to') or '')
    if date_to:
        picklists = picklists.filter(created_at__date__lte=date_to)
    return picklists


@company_admin_required
def orders_list(request):
    """List all orders with search and filter."""
    context = get_base_context(request, 'orders')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    orders = _filtered_orders(customer, request.GET).annotate(
        item_count=Sum('lines__quantity')
    )
    context['search'] = request.GET.get('search', '').strip()
    context['status_filter'] = request.GET.get('status', '')
    context['source_filter'] = request.GET.get('source', '')
    context['date_from'] = request.GET.get('date_from', '')
    context['date_to'] = request.GET.get('date_to', '')

    # Distinct sources for the filter dropdown (only shown when there is
    # more than one, e.g. manual + shopify).
    context['sources'] = list(
        Order.objects.filter(customer=customer)
        .values_list('source', flat=True).distinct().order_by('source')
    )

    # Ordering
    ordering = request.GET.get('order', '-created_at')
    if ordering in ['order_code', '-order_code', 'status', '-status', 'created_at', '-created_at']:
        orders = orders.order_by(ordering)
    context['ordering'] = ordering

    # Pagination
    paginator = Paginator(orders, 25)
    page = request.GET.get('page', 1)
    context['orders'] = paginator.get_page(page)
    context['paginator'] = paginator
    context['querystring'] = _querystring_without_page(request)

    return render(request, 'manage/orders/list.html', context)


@company_admin_required
def orders_bulk_action(request):
    """Handle bulk actions on orders (AJAX): delete, add to queue, remove
    from queue. Accepts either an explicit id list or select_all + the list's
    current filters. In-progress orders are never touched — someone is
    picking them — they are counted and reported as skipped."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)

    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': _("Invalid request.")}, status=400)

    action = data.get('action', '')

    if data.get('select_all'):
        orders = _filtered_orders(customer, data.get('filters') or {})
    else:
        order_ids = data.get('order_ids', [])
        if not order_ids:
            return JsonResponse({'status': 'error', 'message': _("No orders selected.")}, status=400)
        orders = Order.objects.filter(customer=customer, order_id__in=order_ids)
    count = orders.count()
    if not count:
        return JsonResponse({'status': 'error', 'message': _("No orders selected.")}, status=400)

    if action == 'delete':
        deletable = orders.exclude(status='in_progress')
        deleted = deletable.count()
        skipped = count - deleted
        deletable.delete()
        message = ngettext(
            "%(count)s order deleted.",
            "%(count)s orders deleted.",
            deleted) % {'count': deleted}
        if skipped:
            message += " " + ngettext(
                "%(count)s in-progress order skipped.",
                "%(count)s in-progress orders skipped.",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    elif action == 'add_to_queue':
        with transaction.atomic():
            drafts = list(orders.filter(status='draft')
                          .select_for_update().order_by('created_at'))
            max_pos = Order.objects.filter(
                customer=customer,
                status__in=['queued', 'in_progress']
            ).aggregate(max_pos=Max('queue_position'))['max_pos'] or 0
            for position, order in enumerate(drafts, start=max_pos + 1):
                order.status = 'queued'
                order.queue_position = position
            Order.objects.bulk_update(drafts, ['status', 'queue_position'])
        added = len(drafts)
        skipped = count - added
        message = ngettext(
            "%(count)s order added to the queue.",
            "%(count)s orders added to the queue.",
            added) % {'count': added}
        if skipped:
            message += " " + ngettext(
                "%(count)s order skipped (not draft).",
                "%(count)s orders skipped (not draft).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    elif action == 'remove_from_queue':
        removed = orders.filter(status='queued').update(
            status='draft', queue_position=None)
        skipped = count - removed
        message = ngettext(
            "%(count)s order removed from the queue.",
            "%(count)s orders removed from the queue.",
            removed) % {'count': removed}
        if skipped:
            message += " " + ngettext(
                "%(count)s order skipped (not queued).",
                "%(count)s orders skipped (not queued).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    elif action == 'reset_to_draft':
        # The escape hatch for stuck/test orders: unclaim in-progress orders
        # (discarding the active picklist, like the queue unlock does) and put
        # them back to draft, where delete and re-queue are allowed again.
        # Completed and cancelled orders are left alone.
        with transaction.atomic():
            targets = list(orders.filter(status__in=['queued', 'in_progress'])
                           .select_for_update())
            for order in targets:
                if order.status == 'in_progress':
                    # Match on picklist_code as well as the order FK — a
                    # picklist that predates the claim may have order=None.
                    PickList.objects.filter(
                        Q(order=order) | Q(picklist_code=order.order_code),
                        customer=customer,
                        pick_started=True,
                        successful__isnull=True,
                    ).delete()
                order.status = 'draft'
                order.queue_position = None
            Order.objects.bulk_update(targets, ['status', 'queue_position'])
        reset = len(targets)
        skipped = count - reset
        message = ngettext(
            "%(count)s order reset to draft.",
            "%(count)s orders reset to draft.",
            reset) % {'count': reset}
        if skipped:
            message += " " + ngettext(
                "%(count)s order skipped (already draft, completed or cancelled).",
                "%(count)s orders skipped (already draft, completed or cancelled).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    return JsonResponse({'status': 'error', 'message': _("Unknown action.")}, status=400)


@company_admin_required
def order_create(request):
    """Create a new order."""
    context = get_base_context(request, 'orders')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    # Get products for dropdown
    context['products'] = Product.objects.filter(customer=customer, active=True).order_by('code')

    if request.method == 'POST':
        order_code = request.POST.get('order_code', '').strip()
        notes = request.POST.get('notes', '').strip()
        add_to_queue = request.POST.get('add_to_queue') == 'on'

        # Get order lines from form
        product_ids = request.POST.getlist('product_id[]')
        amounts = request.POST.getlist('amount[]')

        errors = []
        if not order_code:
            errors.append(_("Order code is required."))
        elif Order.objects.filter(customer=customer, order_code=order_code).exists():
            errors.append(_("An order with this code already exists."))

        if not product_ids or not any(product_ids):
            errors.append(_("At least one product is required."))

        if errors:
            for error in errors:
                messages.error(request, error)
            context['form_data'] = request.POST
            return render(request, 'manage/orders/form.html', context)

        # Create order
        order = Order.objects.create(
            customer=customer,
            order_code=order_code,
            notes=notes,
            status='queued' if add_to_queue else 'draft'
        )

        # Set queue position if adding to queue
        if add_to_queue:
            max_position = Order.objects.filter(
                customer=customer,
                status__in=['queued', 'in_progress']
            ).aggregate(max_pos=Max('queue_position'))['max_pos'] or 0
            order.queue_position = max_position + 1
            order.save()

        # Create order lines
        for i, product_id in enumerate(product_ids):
            if product_id:
                amount = int(amounts[i]) if i < len(amounts) and amounts[i] else 1
                product = get_object_or_404(Product, product_id=product_id, customer=customer)
                OrderLine.objects.create(
                    order=order,
                    product=product,
                    quantity=amount
                )

        messages.success(request, _("Order '{code}' created successfully.").format(code=order_code))
        return redirect('manage_orders')

    context['is_create'] = True
    return render(request, 'manage/orders/form.html', context)


@company_admin_required
def order_edit(request, order_id):
    """Edit an existing order."""
    context = get_base_context(request, 'orders')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    order = get_object_or_404(Order, order_id=order_id, customer=customer)
    context['order'] = order
    context['order_lines'] = order.lines.select_related('product').all()

    # Get products for dropdown
    context['products'] = Product.objects.filter(customer=customer, active=True).order_by('code')

    if request.method == 'POST':
        order_code = request.POST.get('order_code', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Get order lines from form
        product_ids = request.POST.getlist('product_id[]')
        amounts = request.POST.getlist('amount[]')

        errors = []
        if not order_code:
            errors.append(_("Order code is required."))
        elif Order.objects.filter(customer=customer, order_code=order_code).exclude(order_id=order_id).exists():
            errors.append(_("An order with this code already exists."))

        if not product_ids or not any(product_ids):
            errors.append(_("At least one product is required."))

        if errors:
            for error in errors:
                messages.error(request, error)
            context['form_data'] = request.POST
            return render(request, 'manage/orders/form.html', context)

        # Update order
        order.order_code = order_code
        order.notes = notes
        order.save()

        # Delete existing order lines and create new ones
        order.lines.all().delete()

        for i, product_id in enumerate(product_ids):
            if product_id:
                amount = int(amounts[i]) if i < len(amounts) and amounts[i] else 1
                product = get_object_or_404(Product, product_id=product_id, customer=customer)
                OrderLine.objects.create(
                    order=order,
                    product=product,
                    quantity=amount
                )

        messages.success(request, _("Order '{code}' updated successfully.").format(code=order_code))
        return redirect('manage_orders')

    context['is_create'] = False
    return render(request, 'manage/orders/form.html', context)


@company_admin_required
def order_delete(request, order_id):
    """Delete an order (AJAX)."""
    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    order = get_object_or_404(Order, order_id=order_id, customer=customer)

    if request.method == 'POST':
        code = order.order_code
        order.delete()
        return JsonResponse({'status': 'ok', 'message': _("Order '{code}' deleted.").format(code=code)})

    return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)


@company_admin_required
def orders_import(request):
    """Import orders from CSV."""
    context = get_base_context(request, 'orders')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, _("Please select a CSV file."))
            return render(request, 'manage/orders/import.html', context)

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, _("Please upload a valid CSV file."))
            return render(request, 'manage/orders/import.html', context)

        try:
            rows = read_csv_rows(csv_file, ORDER_CSV_FIELDS)

            created_count = 0
            line_count = 0
            problems = []

            # Group by order_code
            orders_data = {}
            for line_number, row in rows:
                order_code = row['order_code'][:255]
                product_code = row['product_code']
                amount = row['amount']
                notes = row['notes']

                if not order_code or not product_code:
                    problems.append(_("row {row}: missing order code or product code").format(row=line_number))
                    continue

                if order_code not in orders_data:
                    orders_data[order_code] = {
                        'notes': notes,
                        'lines': []
                    }
                orders_data[order_code]['lines'].append({
                    'product_code': product_code,
                    'amount': int(amount) if amount.isdigit() else 1
                })

            # Create orders
            for order_code, data in orders_data.items():
                if Order.objects.filter(customer=customer, order_code=order_code).exists():
                    problems.append(_("order {order} already exists").format(order=order_code))
                    continue

                order = Order.objects.create(
                    customer=customer,
                    order_code=order_code,
                    notes=data['notes'],
                    status='draft'
                )
                created_count += 1

                for line_data in data['lines']:
                    # Barcode aliases resolve too: a row carrying a superseded
                    # EAN must land on the existing product, not be dropped.
                    product = resolve_product(customer, line_data['product_code'])
                    if product is not None:
                        OrderLine.objects.create(
                            order=order,
                            product=product,
                            quantity=line_data['amount']
                        )
                        line_count += 1
                    else:
                        problems.append(_("order {order}: unknown product {product}").format(
                            order=order_code, product=line_data['product_code']))

            if not created_count:
                messages.error(request, _(
                    "No orders were imported: {reasons}"
                ).format(reasons='; '.join(problems[:10]) or _("the file contains no valid rows.")))
                return render(request, 'manage/orders/import.html', context)

            messages.success(request, _("Import completed: {orders} orders created with {lines} lines.").format(
                orders=created_count, lines=line_count
            ))
            if problems:
                messages.warning(request, _("Some rows could not be imported: {reasons}").format(
                    reasons='; '.join(problems[:10])))
            return redirect('manage_orders')

        except CSVImportError as e:
            messages.error(request, str(e))
            return render(request, 'manage/orders/import.html', context)
        except Exception as e:
            messages.error(request, _("Error processing CSV: {error}").format(error=str(e)))
            return render(request, 'manage/orders/import.html', context)

    return render(request, 'manage/orders/import.html', context)


# ============================================
# Queue Management (redirects to existing)
# ============================================

@company_admin_required
def queue_manage(request):
    """Redirect to existing queue management."""
    # We'll integrate this properly later
    from orderpiqrApp.views.queue_views import queue_manage as existing_queue_manage
    return existing_queue_manage(request)


# ============================================
# Picklists (Read-only overview)
# ============================================

@company_admin_required
def picklists_list(request):
    """List all picklists with search and filter."""
    context = get_base_context(request, 'picklists')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    picklists = _filtered_picklists(customer, request.GET).order_by('-created_at')

    # Context for filter bar
    context['status_filter'] = request.GET.get('status', '')
    context['q'] = request.GET.get('q', '').strip()
    context['device_filter'] = request.GET.get('device', '')
    context['date_from'] = request.GET.get('date_from', '')
    context['date_to'] = request.GET.get('date_to', '')

    # Device dropdown: archived devices stay selectable — filtering history by
    # a retired phone is a main reason to archive instead of delete — but sort
    # last and are labelled, so the live fleet comes first.
    context['devices'] = Device.objects.filter(customer=customer).order_by('archived', 'name')

    # Pagination
    paginator = Paginator(picklists, 25)
    page = request.GET.get('page', 1)
    context['picklists'] = paginator.get_page(page)
    context['paginator'] = paginator
    context['querystring'] = _querystring_without_page(request)

    return render(request, 'manage/picklists/list.html', context)


@company_admin_required
def picklist_detail(request, picklist_id):
    """View picklist details (read-only)."""
    context = get_base_context(request, 'picklists')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    picklist = get_object_or_404(PickList, picklist_id=picklist_id, customer=customer)
    context['picklist'] = picklist
    context['product_picks'] = picklist.products.select_related('product').all()

    return render(request, 'manage/picklists/detail.html', context)


@company_admin_required
def picklist_close(request, picklist_id):
    """Admin cleanup for open picklists: mark completed or archive.

    Deliberately no cancel/delete — billing counts picklists, so the row
    always survives. "Complete" only closes the picklist and its linked
    order; it fires no inventory decrement and no platform write-backs
    (an admin closing a stale list is not a real pick).
    """
    if request.method != 'POST':
        return redirect('manage_picklists')

    context = get_base_context(request)
    customer = context['customer']
    if not customer:
        return redirect('manage_dashboard')

    picklist = get_object_or_404(PickList, picklist_id=picklist_id, customer=customer)
    action = request.POST.get('action')
    now = timezone.now()
    stamp = f"{request.user.username} at {timezone.localtime(now).strftime('%Y-%m-%d %H:%M')}"

    if action == 'complete' and picklist.successful is None:
        picklist.successful = True
        if picklist.pick_time:
            picklist.time_taken = now - picklist.pick_time
        note = f"Marked completed by {stamp}"
        picklist.notes = f"{picklist.notes}\n{note}" if picklist.notes else note
        picklist.save()
        # Pending lines on an admin-closed list were never recorded either.
        resolve_pending_picks_to_lost(picklist)
        if picklist.order and picklist.order.status != 'completed':
            picklist.order.status = 'completed'
            picklist.order.completed_at = now
            picklist.order.save(update_fields=['status', 'completed_at'])
        messages.success(request, _("Picklist marked as completed."))
    elif action == 'archive' and not picklist.archived:
        picklist.archived = True
        note = f"Archived by {stamp}"
        picklist.notes = f"{picklist.notes}\n{note}" if picklist.notes else note
        picklist.save()
        messages.success(request, _("Picklist archived."))

    next_url = request.POST.get('next', '')
    if next_url == 'health':
        return redirect('manage_health')
    if next_url == 'detail':
        return redirect('manage_picklist_detail', picklist_id=picklist.picklist_id)
    return redirect('manage_picklists')


@company_admin_required
def picklists_bulk_action(request):
    """Handle bulk actions on picklists (AJAX): complete or archive. Accepts
    either an explicit id list or select_all + the list's current filters.
    Only picklists that meet the action's precondition are touched; others are
    counted and reported as skipped."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)

    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': _("Invalid request.")}, status=400)

    action = data.get('action', '')

    if data.get('select_all'):
        picklists = _filtered_picklists(customer, data.get('filters') or {})
    else:
        picklist_ids = data.get('picklist_ids', [])
        if not picklist_ids:
            return JsonResponse({'status': 'error', 'message': _("No picklists selected.")}, status=400)
        picklists = PickList.objects.filter(customer=customer, picklist_id__in=picklist_ids)
    count = picklists.count()
    if not count:
        return JsonResponse({'status': 'error', 'message': _("No picklists selected.")}, status=400)

    now = timezone.now()

    if action == 'complete':
        # Only complete picklists that haven't been marked complete/failed yet
        completable = picklists.filter(successful__isnull=True)
        completed = 0
        for picklist in completable:
            picklist.successful = True
            if picklist.pick_time:
                picklist.time_taken = now - picklist.pick_time
            stamp = f"{request.user.username} at {timezone.localtime(now).strftime('%Y-%m-%d %H:%M')}"
            note = f"Marked completed by {stamp}"
            picklist.notes = f"{picklist.notes}\n{note}" if picklist.notes else note
            picklist.save()
            resolve_pending_picks_to_lost(picklist)
            # Update linked order if it exists and isn't already completed
            if picklist.order and picklist.order.status != 'completed':
                picklist.order.status = 'completed'
                picklist.order.completed_at = now
                picklist.order.save(update_fields=['status', 'completed_at'])
            completed += 1
        skipped = count - completed
        message = ngettext(
            "%(count)s picklist marked as completed.",
            "%(count)s picklists marked as completed.",
            completed) % {'count': completed}
        if skipped:
            message += " " + ngettext(
                "%(count)s picklist skipped (already marked).",
                "%(count)s picklists skipped (already marked).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    elif action == 'archive':
        # Only archive picklists that aren't already archived
        archivable = picklists.filter(archived=False)
        archived = 0
        for picklist in archivable:
            picklist.archived = True
            stamp = f"{request.user.username} at {timezone.localtime(now).strftime('%Y-%m-%d %H:%M')}"
            note = f"Archived by {stamp}"
            picklist.notes = f"{picklist.notes}\n{note}" if picklist.notes else note
            picklist.save()
            archived += 1
        skipped = count - archived
        message = ngettext(
            "%(count)s picklist archived.",
            "%(count)s picklists archived.",
            archived) % {'count': archived}
        if skipped:
            message += " " + ngettext(
                "%(count)s picklist skipped (already archived).",
                "%(count)s picklists skipped (already archived).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    else:
        return JsonResponse({'status': 'error', 'message': _("Invalid action.")}, status=400)


# ============================================
# Pick-flow Health
# ============================================

def _health_window(request):
    """Resolve the dashboard's time window from the query string.

    Thin wrapper over `utils.health.health_window`, which takes the dict-like
    of query params directly so the API endpoint can share the exact same
    logic without a request object.
    """
    return health_window(request.GET)


# Which event types roll up into each headline tile. Severity answers "how bad",
# these answer "what kind of problem is it" — the split that lets a blocking
# lockout stop hiding behind a pile of routine unknown-barcode warnings.
HEALTH_TILE_TYPES = {
    'blocking': ['picklist_rejected', 'sync_error', 'auth_bounce'],
    'scanning': ['unknown_product', 'wrong_product', 'picklist_parse_error'],
    'overrides': ['manual_override'],
    'app': ['client_error', 'camera_error', 'app_lifecycle', 'lock_takeover'],
}


def _add_health_tiles(context, window):
    """Headline counts per problem kind, each one a link that filters the list."""
    counts = dict(window.values_list('event_type').annotate(n=Count('id'))
                  .values_list('event_type', 'n'))
    context['tiles'] = {
        key: sum(counts.get(event_type, 0) for event_type in types)
        for key, types in HEALTH_TILE_TYPES.items()
    }
    context['severity_counts'] = dict(
        window.values_list('severity').annotate(n=Count('id')).values_list('severity', 'n'))

    # The slug that distinguishes cases sharing an event_type. Before this
    # existed, three different failures were all just "unknown_product" and the
    # real difference lived in free text nothing could group by.
    context['top_reasons'] = list(
        window.exclude(reason='')
        .values('event_type', 'reason')
        .annotate(count=Count('id'))
        .order_by('-count')[:10])


def _add_device_breakdown(context, customer, window, start, end):
    """One row per device: the table that turns "the app crashes" into "that phone".

    Device 630 overrode 27.6% of its lines on a shift where another phone sat
    at 0.3% — invisible until the numbers are put side by side.
    """
    rows = {}
    for entry in (window.values('device_id', 'device__name', 'event_type')
                  .annotate(n=Count('id'))):
        device_id = entry['device_id']
        row = rows.setdefault(device_id, {
            'device_id': device_id,
            'name': (entry['device__name'] or '').strip() or _('Unknown device'),
            'errors': 0, 'overrides': 0, 'restarts': 0, 'bounces': 0, 'total': 0,
        })
        count = entry['n']
        row['total'] += count
        event_type = entry['event_type']
        if event_type == 'manual_override':
            row['overrides'] += count
        elif event_type == 'app_lifecycle':
            row['restarts'] += count
        elif event_type == 'auth_bounce':
            row['bounces'] += count
        elif event_type in ('client_error', 'camera_error', 'sync_error', 'picklist_rejected'):
            row['errors'] += count

    lists_done = dict(
        PickList.objects
        .filter(customer=customer, pick_time__gte=start, pick_time__lte=end)
        .values_list('device_id').annotate(n=Count('picklist_id'))
        .values_list('device_id', 'n'))

    devices = {d.device_id: d for d in Device.objects.filter(customer=customer)}
    for device_id, row in rows.items():
        device = devices.get(device_id)
        row['lists'] = lists_done.get(device_id, 0)
        row['last_seen'] = device.last_login if device else None
        row['browser'] = device.browser if device else ''
        row['os'] = device.os if device else ''
        row['os_version'] = device.os_version if device else ''
        row['display_mode'] = device.get_display_mode_display() if device and device.display_mode else ''
        row['installed'] = bool(device and device.display_mode == 'standalone')
        row['browser_tab'] = bool(device and device.display_mode == 'browser')
        row['build'] = device.last_build_id if device else ''
        # Overrides per list is the comparable number — raw counts just track
        # who picked most.
        row['override_rate'] = round(row['overrides'] / row['lists'], 1) if row['lists'] else None

    context['device_rows'] = sorted(
        rows.values(), key=lambda r: (r['errors'] + r['bounces'], r['overrides']), reverse=True)


def _add_problem_codes(context, customer, window):
    """Codes that need attention, with the cause named and a fix to click.

    This replaces a "Top Problem Codes" table that listed a code, a single
    event count, and the word "Known product" where an action belonged. It was
    worse than unhelpful: it summed two opposite problems into one number.
    On Healthy Fridge's real data, 8721352510154 was 26 manual overrides out of
    29 (the label does not scan) while 8721352510079 was 46 unknown_product out
    of 52 (scanned into an order it is not part of). Same row count, opposite
    causes, opposite fixes.
    """
    rows = {}
    for entry in (window.exclude(scanned_code='')
                  .values('scanned_code', 'event_type')
                  .annotate(n=Count('id'))):
        row = rows.setdefault(entry['scanned_code'], {
            'code': entry['scanned_code'],
            'total': 0, 'overrides': 0, 'not_found': 0, 'not_recorded': 0, 'unreadable': 0,
        })
        count = entry['n']
        row['total'] += count
        event_type = entry['event_type']
        if event_type == 'manual_override':
            row['overrides'] += count
        elif event_type == 'unknown_product':
            row['not_found'] += count
        elif event_type == 'sync_error':
            row['not_recorded'] += count
        elif event_type in ('wrong_product', 'picklist_parse_error'):
            row['unreadable'] += count

    top = sorted(rows.values(), key=lambda r: -r['total'])[:10]
    codes = [r['code'] for r in top]

    products = {p.code: p for p in Product.objects.filter(customer=customer, code__in=codes)}
    # An alias is a known product too — offering "Add as product" for one would
    # dead-end on the duplicate-code check.
    aliases = {b.code: b.product for b in ProductBarcode.objects
               .filter(customer=customer, code__in=codes).select_related('product')}

    for row in top:
        product = products.get(row['code']) or aliases.get(row['code'])
        row['product'] = product
        row['is_alias'] = row['code'] in aliases and row['code'] not in products

        if product is None:
            # Nothing in the catalog answers to this code.
            row['diagnosis'] = 'unknown_code'
        elif row['overrides'] >= max(row['not_found'], row['not_recorded'], row['unreadable']):
            # Pickers keep confirming this line by hand, which is them telling
            # us the barcode on the label does not scan.
            row['diagnosis'] = 'not_scanning'
        elif row['not_recorded'] >= max(row['not_found'], row['unreadable']):
            row['diagnosis'] = 'not_recorded'
        elif row['not_found'] >= row['unreadable']:
            # A code the catalog knows, reported unknown: it was scanned for an
            # order it is not part of, or every unit was already picked.
            row['diagnosis'] = 'not_in_order'
        else:
            row['diagnosis'] = 'unreadable'

    context['problem_codes'] = top


def _add_pick_outcomes(context, customer, start, end):
    """Did the work actually get recorded? The metric that measures real harm.

    Thin wrapper over `utils.health.pick_outcomes`, which returns the dict
    instead of mutating a view context so the API endpoint can reuse it too.
    """
    outcomes, current_build = pick_outcomes(customer, start, end)
    context['current_build'] = current_build
    context['outcomes'] = outcomes


@company_admin_required
def health_list(request):
    """Pick-flow health: what went wrong for pickers, on which device, when.

    Built to answer a complaint like "the app crashed and kicked people out"
    without a developer: the live strip says whether it is happening now, the
    tiles say what kind of problem it is, and the per-device table says whether
    it is one phone or all of them.
    """
    context = get_base_context(request, 'health')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    start, end, preset, window_label = _health_window(request)
    context.update({
        'preset': preset,
        'window_label': window_label,
        'window_start': start,
        'window_end': end,
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
    })

    window = ScanEvent.objects.filter(
        customer=customer, created_at__gte=start, created_at__lte=end)

    events = (ScanEvent.objects
              .filter(customer=customer, created_at__gte=start, created_at__lte=end)
              .select_related('device').order_by('-created_at'))

    # Filters
    event_type = request.GET.get('event_type')
    if event_type:
        events = events.filter(event_type=event_type)
        context['event_type_filter'] = event_type

    severity = request.GET.get('severity')
    if severity in dict(ScanEvent.SEVERITIES):
        events = events.filter(severity=severity)
        context['severity_filter'] = severity

    tile = request.GET.get('tile')
    if tile in HEALTH_TILE_TYPES:
        events = events.filter(event_type__in=HEALTH_TILE_TYPES[tile])
        context['tile_filter'] = tile

    device_filter = request.GET.get('device')
    if device_filter and device_filter.isdigit():
        events = events.filter(device_id=int(device_filter))
        context['device_filter'] = int(device_filter)

    context['event_types'] = ScanEvent.EVENT_TYPES
    context['severities'] = ScanEvent.SEVERITIES

    _add_health_tiles(context, window)
    _add_device_breakdown(context, customer, window, start, end)
    _add_pick_outcomes(context, customer, start, end)

    _add_problem_codes(context, customer, window)

    # Deliberately NOT window-filtered: a stuck list is a thing to go and fix
    # now, not a historical statistic. Labelled as such on the page, because
    # silently ignoring the date filter is what made this card confusing.
    stale = list(PickList.objects.filter(
        customer=customer,
        pick_started=True,
        successful__isnull=True,
        archived=False,
        pick_time__lt=timezone.now() - timedelta(hours=4)
    ).select_related('order', 'device').order_by('pick_time'))

    # How much work is actually trapped in each one, and whether the picker had
    # to keep restarting it — both already stored, neither ever shown.
    pending_counts = dict(
        ProductPick.objects
        .filter(picklist__in=stale, outcome='pending')
        .values_list('picklist')
        .annotate(n=Count('id'))
        .values_list('picklist', 'n'))
    for picklist in stale:
        picklist.pending_lines = pending_counts.get(picklist.picklist_id, 0)
        picklist.restart_count = (picklist.notes or '').count('Restarted by device')
    context['stale_picklists'] = stale
    context['stale_pending_lines'] = sum(p.pending_lines for p in stale)

    # Pagination
    paginator = Paginator(events, 25)
    page = request.GET.get('page', 1)
    context['events'] = paginator.get_page(page)
    context['paginator'] = paginator
    context['querystring'] = _querystring_without_page(request)

    return render(request, 'manage/health/list.html', context)


# ============================================
# Devices (Read-only overview)
# ============================================

def _filtered_devices(customer, params):
    """Device queryset for the given filter params (show, name search, last-seen
    range). Shared by the list view and the bulk endpoint's select-all mode so
    "select everything matching this filter" means exactly what the list shows."""
    devices = Device.objects.filter(customer=customer)
    show = params.get('show') or 'active'
    if show not in ('active', 'archived', 'all'):
        show = 'active'
    if show == 'active':
        devices = devices.filter(archived=False)
    elif show == 'archived':
        devices = devices.filter(archived=True)
    search = (params.get('q') or '').strip()
    if search:
        devices = devices.filter(
            Q(name__icontains=search) | Q(description__icontains=search)
            | Q(user__username__icontains=search))
    # Last-seen range: "not seen since the summer" is the archive-candidate
    # filter, so this ranges over activity, not registration date.
    seen_from = parse_date(params.get('seen_from') or '')
    if seen_from:
        devices = devices.filter(last_login__date__gte=seen_from)
    seen_to = parse_date(params.get('seen_to') or '')
    if seen_to:
        devices = devices.filter(last_login__date__lte=seen_to)
    return devices


@company_admin_required
def devices_list(request):
    """What each picker's phone actually is, and how it is behaving.

    This page used to show a name, an online dot and a lifetime list count,
    which could not answer any of the questions people actually ask: is it an
    old phone, is it running in a browser tab instead of the installed app, is
    it stuck on an old build, is it the one producing all the errors.
    """
    context = get_base_context(request, 'devices')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    show = request.GET.get('show', 'active')
    if show not in ('active', 'archived', 'all'):
        show = 'active'

    all_devices = Device.objects.filter(customer=customer)
    archived_count = all_devices.filter(archived=True).count()
    active_count = all_devices.filter(archived=False).count()

    # Deleting a device cascades its picklists away and billing counts those,
    # so the template needs this to know whether Delete may be offered at all.
    devices = list(_filtered_devices(customer, request.GET)
                   .select_related('user')
                   .annotate(picklist_count=Count('picklist')))

    # Errors and overrides per device over the last 24 hours, in one query.
    recent_events = (ScanEvent.objects
                     .filter(customer=customer, created_at__gte=day_ago)
                     .values('device_id', 'event_type')
                     .annotate(n=Count('id')))
    per_device = {}
    for entry in recent_events:
        bucket = per_device.setdefault(entry['device_id'], {})
        bucket[entry['event_type']] = entry['n']

    lists_week = dict(
        PickList.objects
        .filter(customer=customer, pick_time__gte=week_ago)
        .values_list('device_id').annotate(n=Count('picklist_id'))
        .values_list('device_id', 'n'))

    current_build = get_build_id()
    for device in devices:
        counts = per_device.get(device.device_id, {})
        device.is_active = bool(device.last_login and (now - device.last_login) < timedelta(minutes=15))
        device.errors_today = (counts.get('client_error', 0) + counts.get('camera_error', 0)
                               + counts.get('sync_error', 0) + counts.get('picklist_rejected', 0))
        device.overrides_today = counts.get('manual_override', 0)
        device.restarts_today = counts.get('app_lifecycle', 0)
        device.bounces_today = counts.get('auth_bounce', 0)
        # The one number shown in the table; the full breakdown (incl. restarts
        # and overrides, which are activity rather than problems) is the title.
        device.issues_today = device.errors_today + device.bounces_today
        device.lists_week = lists_week.get(device.device_id, 0)
        # An outdated build is only meaningful for a device we have heard from
        # recently; a phone last seen in September is simply gone.
        device.build_outdated = bool(
            device.last_build_id and current_build
            and device.last_build_id != current_build
            and device.last_login and device.last_login >= week_ago)
        device.unnamed = device.name.startswith('Auto-created device') or not device.name.strip()

    # Problem devices first, then most recently seen.
    devices.sort(key=lambda d: (
        -(d.errors_today + d.bounces_today),
        -d.overrides_today,
        -(d.last_login.timestamp() if d.last_login else 0),
    ))

    # Several rows for one human is the fingerprint-churn signature: a device
    # identity is only a localStorage UUID, so storage eviction mints a new one
    # and locks the picker out of their own list.
    names = Counter((d.name or '').strip().lower() for d in devices if (d.name or '').strip())
    for device in devices:
        device.possible_duplicate = names[(device.name or '').strip().lower()] > 1

    context['current_build'] = current_build
    context['duplicate_count'] = sum(1 for d in devices if d.possible_duplicate)
    context['browser_tab_count'] = sum(1 for d in devices if d.display_mode == 'browser')
    context['unknown_mode_count'] = sum(1 for d in devices if not d.display_mode)
    context['show'] = show
    context['active_count'] = active_count
    context['archived_count'] = archived_count

    # Counted before pagination: the bulk bar's "select all N matching" must
    # mean the whole filtered set, not the visible page.
    context['device_count'] = len(devices)
    paginator = Paginator(devices, 25)
    context['devices'] = paginator.get_page(request.GET.get('page', 1))
    context['paginator'] = paginator
    context['querystring'] = _querystring_without_page(request)
    context['q'] = (request.GET.get('q') or '').strip()
    context['seen_from'] = request.GET.get('seen_from', '')
    context['seen_to'] = request.GET.get('seen_to', '')

    return render(request, 'manage/devices/list.html', context)


def _devices_redirect(request):
    """Back to the devices list on the filter the admin was looking at."""
    show = request.POST.get('show', '')
    url = reverse('manage_devices')
    if show in ('archived', 'all'):
        return redirect(f"{url}?show={show}")
    return redirect(url)


@company_admin_required
def device_archive(request, device_id):
    """Hide a dead phone from the devices list without touching its history.

    Archiving is reversible and is not a block: the device keeps working, and
    any activity un-archives it again (see utils.devices.touch_device).
    """
    if request.method != 'POST':
        return redirect('manage_devices')

    context = get_base_context(request)
    customer = context['customer']
    if not customer:
        return redirect('manage_dashboard')

    device = get_object_or_404(Device, device_id=device_id, customer=customer)
    if not device.archived:
        device.archived = True
        device.save(update_fields=['archived'])
    messages.success(request, _("Device archived."))
    return _devices_redirect(request)


@company_admin_required
def device_restore(request, device_id):
    """Bring an archived device back onto the active list."""
    if request.method != 'POST':
        return redirect('manage_devices')

    context = get_base_context(request)
    customer = context['customer']
    if not customer:
        return redirect('manage_dashboard')

    device = get_object_or_404(Device, device_id=device_id, customer=customer)
    if device.archived:
        device.archived = False
        device.save(update_fields=['archived'])
    messages.success(request, _("Device restored."))
    return _devices_redirect(request)


@company_admin_required
def device_delete(request, device_id):
    """Delete a device, but only one that never picked anything.

    PickList.device cascades, so deleting a device with history would silently
    destroy the picklists billing counts. That is re-checked here and not left
    to the template: the only safe cleanup for a device with history is archive.
    """
    if request.method != 'POST':
        return redirect('manage_devices')

    context = get_base_context(request)
    customer = context['customer']
    if not customer:
        return redirect('manage_dashboard')

    device = get_object_or_404(Device, device_id=device_id, customer=customer)
    if PickList.objects.filter(device=device).exists():
        messages.error(request, _("Devices with picked lists can only be archived."))
        return _devices_redirect(request)

    device.delete()
    messages.success(request, _("Device deleted."))
    return _devices_redirect(request)


@company_admin_required
def devices_bulk_action(request):
    """Handle bulk actions on devices (AJAX): archive, restore, delete.
    Accepts either an explicit id list or select_all + the list's current
    filters. Delete skips devices with picked lists — their deletion would
    cascade into billed history — and reports them as archive-only."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)

    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': _("Invalid request.")}, status=400)

    action = data.get('action', '')

    if data.get('select_all'):
        devices = _filtered_devices(customer, data.get('filters') or {})
    else:
        device_ids = data.get('device_ids', [])
        if not device_ids:
            return JsonResponse({'status': 'error', 'message': _("No devices selected.")}, status=400)
        devices = Device.objects.filter(customer=customer, device_id__in=device_ids)
    count = devices.count()
    if not count:
        return JsonResponse({'status': 'error', 'message': _("No devices selected.")}, status=400)

    if action == 'archive':
        archived = devices.filter(archived=False).update(archived=True)
        skipped = count - archived
        message = ngettext(
            "%(count)s device archived.",
            "%(count)s devices archived.",
            archived) % {'count': archived}
        if skipped:
            message += " " + ngettext(
                "%(count)s device skipped (already archived).",
                "%(count)s devices skipped (already archived).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    elif action == 'restore':
        restored = devices.filter(archived=True).update(archived=False)
        skipped = count - restored
        message = ngettext(
            "%(count)s device restored.",
            "%(count)s devices restored.",
            restored) % {'count': restored}
        if skipped:
            message += " " + ngettext(
                "%(count)s device skipped (not archived).",
                "%(count)s devices skipped (not archived).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    elif action == 'delete':
        deletable = devices.filter(picklist__isnull=True)
        deleted = deletable.count()
        deletable.delete()
        skipped = count - deleted
        message = ngettext(
            "%(count)s device deleted.",
            "%(count)s devices deleted.",
            deleted) % {'count': deleted}
        if skipped:
            message += " " + ngettext(
                "%(count)s device with picked lists skipped (archive it instead).",
                "%(count)s devices with picked lists skipped (archive them instead).",
                skipped) % {'count': skipped}
        return JsonResponse({'status': 'ok', 'message': message})

    else:
        return JsonResponse({'status': 'error', 'message': _("Invalid action.")}, status=400)


# ============================================
# Profile
# ============================================

def _picker_users(customer):
    return (User.objects
            .filter(userprofile__customer=customer, groups__name='orderpicker')
            .order_by('username'))


@company_admin_required
def profile(request):
    """View and edit user profile, plus the customer's picker accounts."""
    context = get_base_context(request, 'profile')
    customer = context['customer']
    user = request.user
    # Set only by 'create_picker_qr': the raw token is never stored, so the
    # page must render it once instead of redirecting.
    new_qr = None

    if request.method == 'POST':
        action = request.POST.get('action', 'update_profile')

        if action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()

            errors = []
            if not first_name:
                errors.append(_("First name is required."))
            if not email:
                errors.append(_("Email is required."))

            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                user.save()
                messages.success(request, _("Profile updated successfully."))

        elif action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            errors = []
            if not check_password(current_password, user.password):
                errors.append(_("Current password is incorrect."))
            if len(new_password) < 8:
                errors.append(_("New password must be at least 8 characters."))
            if new_password != confirm_password:
                errors.append(_("New passwords do not match."))

            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)  # Keep user logged in
                messages.success(request, _("Password changed successfully."))

        elif action == 'set_picker_password' and customer:
            picker_id = request.POST.get('picker_id', '')
            new_password = request.POST.get('picker_password', '')
            picker = _picker_users(customer).filter(pk=picker_id).first()
            if picker is None:
                messages.error(request, _("Picker account not found."))
            elif len(new_password) < 8:
                messages.error(request, _("Password must be at least 8 characters."))
            else:
                picker.set_password(new_password)
                picker.save(update_fields=['password'])
                messages.success(request, _(
                    "Password for picker account '{username}' updated."
                ).format(username=picker.username))

        elif action == 'create_picker' and customer:
            from django.contrib.auth.models import Group
            from orderpiqrApp.models import UserProfile
            username = request.POST.get('picker_username', '').strip()
            new_password = request.POST.get('picker_password', '')
            if not username:
                messages.error(request, _("Username is required."))
            elif User.objects.filter(username=username).exists():
                messages.error(request, _("This username is already taken."))
            elif len(new_password) < 8:
                messages.error(request, _("Password must be at least 8 characters."))
            else:
                picker = User.objects.create_user(username=username, password=new_password)
                group, _created = Group.objects.get_or_create(name='orderpicker')
                picker.groups.add(group)
                UserProfile.objects.create(user=picker, customer=customer)
                messages.success(request, _(
                    "Picker account '{username}' created."
                ).format(username=username))

        elif action == 'create_picker_qr' and customer:
            # _picker_users already scopes to this customer and the orderpicker
            # group, so an id from another tenant simply finds nothing.
            picker = _picker_users(customer).filter(pk=request.POST.get('picker_id', '')).first()
            if picker is None:
                messages.error(request, _("Picker account not found."))
            else:
                # Anything unrecognised becomes blank, i.e. follow the company
                # setting — never a page the picker has no feature for.
                start_page = request.POST.get('start_page', '')
                if start_page not in (SCAN, QUEUE):
                    start_page = ''
                token, raw_token = issue_token(
                    picker, customer, created_by=user, start_page=start_page)
                new_qr = {
                    'picker': picker,
                    'token': token,
                    'url': login_url(raw_token),
                }
                messages.success(request, _(
                    "Login QR created for '{username}'. Print it now – it cannot be "
                    "shown again."
                ).format(username=picker.username))

        elif action == 'revoke_picker_qr' and customer:
            picker = _picker_users(customer).filter(pk=request.POST.get('picker_id', '')).first()
            if picker is None:
                messages.error(request, _("Picker account not found."))
            else:
                token = active_token(picker)
                if token is not None:
                    token.revoke()
                messages.success(request, _(
                    "Login QR for '{username}' revoked. Printed copies no longer work."
                ).format(username=picker.username))

        if new_qr is None:
            return redirect('manage_profile')

    pickers = list(_picker_users(customer)) if customer else []
    for picker in pickers:
        picker.active_qr = active_token(picker)

    context['picker_users'] = pickers
    context['new_qr'] = new_qr
    context['start_page_choices'] = TOKEN_START_PAGE_CHOICES
    return render(request, 'manage/profile.html', context)


# ============================================
# Customer Settings
# ============================================

@company_admin_required
def settings_view(request):
    """View and edit customer settings."""
    context = get_base_context(request, 'settings')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    # Get all setting definitions
    setting_definitions = SettingDefinition.objects.all().order_by('label')

    # Get current customer values
    customer_values = {
        cv.definition.key: cv.value
        for cv in CustomerSettingValue.objects.filter(customer=customer).select_related('definition')
    }

    # Build settings list with current values
    settings_list = []
    for definition in setting_definitions:
        current_value = customer_values.get(definition.key, definition.default_value or '')
        settings_list.append({
            'definition': definition,
            'value': current_value,
            'casted_value': definition.cast_value(current_value) if current_value else None,
        })

    context['settings_list'] = settings_list

    if request.method == 'POST':
        # Update settings - only allow changes for settings with options or boolean type
        for definition in setting_definitions:
            # Only process settings that users can change (have options or are boolean)
            if not definition.options and definition.setting_type != SettingDefinition.SettingType.BOOLEAN:
                continue

            field_name = f'setting_{definition.key}'
            new_value = request.POST.get(field_name, '').strip()

            # Handle boolean fields (checkboxes)
            if definition.setting_type == SettingDefinition.SettingType.BOOLEAN:
                new_value = 'true' if request.POST.get(field_name) == 'on' else 'false'

            # Validate that value is one of the allowed options (if options exist)
            if definition.options:
                allowed_values = [opt['value'] for opt in definition.options]
                if new_value not in allowed_values:
                    continue  # Skip invalid values

            # Update or create customer setting value
            if new_value:
                CustomerSettingValue.objects.update_or_create(
                    customer=customer,
                    definition=definition,
                    defaults={'value': new_value}
                )
            else:
                # Remove custom value to use default
                CustomerSettingValue.objects.filter(
                    customer=customer,
                    definition=definition
                ).delete()

        messages.success(request, _("Settings saved successfully."))
        return redirect('manage_settings')

    return render(request, 'manage/settings.html', context)


# ============================================
# Inventory Management
# ============================================

@company_admin_required
def inventory_logs_list(request):
    """List all inventory log entries with filtering."""
    context = get_base_context(request, 'inventory')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    if not is_inventory_enabled(customer):
        messages.warning(request, _("Inventory management is not enabled for your account."))
        return redirect('manage_settings')

    logs = InventoryLog.objects.filter(
        product__customer=customer,
        deleted=False  # Exclude soft-deleted logs
    ).select_related('product', 'user', 'device').order_by('-created_at')

    # Filters
    product_id = request.GET.get('product')
    if product_id:
        logs = logs.filter(product_id=product_id)
        context['product_filter'] = int(product_id)

    user_id = request.GET.get('user')
    if user_id:
        logs = logs.filter(user_id=user_id)
        context['user_filter'] = int(user_id)

    reason = request.GET.get('reason')
    if reason:
        logs = logs.filter(reason=reason)
        context['reason_filter'] = reason

    date_from = request.GET.get('date_from')
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)
        context['date_from'] = date_from

    date_to = request.GET.get('date_to')
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)
        context['date_to'] = date_to

    # Get filter options
    products = Product.objects.filter(customer=customer).order_by('code')
    context['products'] = products
    context['products_json'] = json.dumps([
        {'id': p.product_id, 'code': p.code, 'description': p.description}
        for p in products
    ])
    context['users'] = User.objects.filter(userprofile__customer=customer).order_by('username')
    context['reasons'] = InventoryLog.Reason.choices

    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get('page', 1)
    context['logs'] = paginator.get_page(page)
    context['paginator'] = paginator

    return render(request, 'manage/inventory/logs.html', context)


@company_admin_required
def inventory_logs_bulk_delete(request):
    """Bulk soft-delete inventory logs (AJAX)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': _("Invalid request method.")}, status=405)

    customer = get_customer_from_user(request.user)
    if not customer:
        return JsonResponse({'status': 'error', 'message': _("No customer found.")}, status=400)

    if not is_inventory_enabled(customer):
        return JsonResponse({'status': 'error', 'message': _("Inventory management is not enabled.")}, status=403)

    try:
        data = json.loads(request.body)
        log_ids = data.get('log_ids', [])
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': _("Invalid request.")}, status=400)

    if not log_ids:
        return JsonResponse({'status': 'error', 'message': _("No logs selected.")}, status=400)

    # Get the logs to delete and revert their changes
    logs_to_delete = InventoryLog.objects.filter(
        log_id__in=log_ids,
        product__customer=customer,
        deleted=False
    ).select_related('product')

    if not logs_to_delete.exists():
        return JsonResponse({'status': 'error', 'message': _("No valid logs found.")}, status=404)

    # Use transaction to ensure atomicity
    from django.db import transaction
    with transaction.atomic():
        deleted_count = 0
        for log in logs_to_delete:
            # Revert the inventory change
            # The change was: old_quantity -> new_quantity
            # To revert: subtract the change that was made
            change_made = log.new_quantity - log.old_quantity
            log.product.inventory_quantity = max(0, log.product.inventory_quantity - change_made)
            log.product.save(update_fields=['inventory_quantity'])

            # Soft delete the log
            log.deleted = True
            log.deleted_at = timezone.now()
            log.deleted_by = request.user
            log.save(update_fields=['deleted', 'deleted_at', 'deleted_by'])
            deleted_count += 1

    return JsonResponse({
        'status': 'ok',
        'message': ngettext(
            "%(count)s log entry deleted and inventory reverted.",
            "%(count)s log entries deleted and inventory reverted.",
            deleted_count) % {'count': deleted_count},
        'deleted_count': deleted_count
    })


@company_admin_required
def inventory_logs_export(request):
    """Export inventory logs to CSV."""
    customer = get_customer_from_user(request.user)
    if not customer:
        return redirect('manage_dashboard')

    if not is_inventory_enabled(customer):
        messages.warning(request, _("Inventory management is not enabled."))
        return redirect('manage_settings')

    logs = InventoryLog.objects.filter(
        product__customer=customer
    ).select_related('product', 'user', 'device').order_by('-created_at')

    # Apply same filters as list view
    product_id = request.GET.get('product')
    if product_id:
        logs = logs.filter(product_id=product_id)

    user_id = request.GET.get('user')
    if user_id:
        logs = logs.filter(user_id=user_id)

    reason = request.GET.get('reason')
    if reason:
        logs = logs.filter(reason=reason)

    date_from = request.GET.get('date_from')
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to')
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_logs.csv"'

    writer = csv.writer(response)
    writer.writerow([
        _('Date/Time'), _('Product Code'), _('Product Description'),
        _('Old Qty'), _('New Qty'), _('Change'), _('Type'), _('Reason'),
        _('User'), _('Device'), _('Notes')
    ])

    for log in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.product.code,
            log.product.description,
            log.old_quantity,
            log.new_quantity,
            log.quantity_change,
            log.get_change_type_display(),
            log.get_reason_display(),
            log.user.get_full_name() if log.user else '',
            log.device.name if log.device else '',
            log.notes or ''
        ])

    return response


@company_admin_required
def inventory_add_correction(request):
    """Add a correction entry for a product."""
    context = get_base_context(request, 'inventory')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    if not is_inventory_enabled(customer):
        messages.warning(request, _("Inventory management is not enabled."))
        return redirect('manage_settings')

    context['products'] = Product.objects.filter(customer=customer, active=True).order_by('code')
    context['reasons'] = InventoryLog.Reason.choices
    context['change_types'] = InventoryLog.ChangeType.choices

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        change_type = request.POST.get('change_type')
        value = request.POST.get('value')
        reason = request.POST.get('reason')
        notes = request.POST.get('notes', '')

        try:
            product = Product.objects.get(product_id=product_id, customer=customer)
            value = int(value)

            modify_inventory(
                product=product,
                user=request.user,
                change_type=change_type,
                reason=reason,
                value=value,
                notes=notes
            )

            messages.success(request, _("Inventory correction added successfully."))
            return redirect('manage_inventory_logs')

        except Product.DoesNotExist:
            messages.error(request, _("Product not found."))
        except (TypeError, ValueError):
            messages.error(request, _("Invalid quantity value."))

    return render(request, 'manage/inventory/add_correction.html', context)


# ============================================
# Logout
# ============================================

@company_admin_required
def logout_view(request):
    """Log out the current user."""
    logout(request)
    messages.success(request, _("You have been logged out successfully."))
    return redirect('login')

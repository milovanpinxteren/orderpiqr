"""
Custom Admin Management Views

A user-friendly custom admin interface for company administrators.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum, Max
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext as _
from datetime import timedelta
import json
import csv
import io

from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.hashers import check_password

from orderpiqrApp.utils.decorators import company_admin_required
from orderpiqrApp.models import Product, Order, OrderLine, PickList, Device, CustomerSettingValue, SettingDefinition


def get_customer_from_user(user):
    """Get the customer associated with the user."""
    if hasattr(user, 'userprofile') and user.userprofile.customer:
        return user.userprofile.customer
    return None


def get_base_context(request, active_nav='dashboard'):
    """Get the base context for all manage views."""
    customer = get_customer_from_user(request.user)
    return {
        'user': request.user,
        'customer': customer,
        'active_nav': active_nav,
    }


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

@company_admin_required
def products_list(request):
    """List all products with search and filter."""
    context = get_base_context(request, 'products')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    # Get products
    products = Product.objects.filter(customer=customer)

    # Search
    search = request.GET.get('search', '').strip()
    if search:
        products = products.filter(
            Q(code__icontains=search) |
            Q(description__icontains=search) |
            Q(location__icontains=search)
        )
        context['search'] = search

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        products = products.filter(active=True)
    elif status_filter == 'inactive':
        products = products.filter(active=False)
    context['status_filter'] = status_filter

    # Filter by location
    location_filter = request.GET.get('location', '')
    if location_filter:
        products = products.filter(location=location_filter)
    context['location_filter'] = location_filter

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

        errors = []
        if not code:
            errors.append(_("Product code is required."))
        elif Product.objects.filter(customer=customer, code=code).exists():
            errors.append(_("A product with this code already exists."))
        if not description:
            errors.append(_("Description is required."))

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
        messages.success(request, _("Product '{code}' created successfully.").format(code=code))
        return redirect('manage_products')

    context['is_create'] = True
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

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        location = request.POST.get('location', '').strip()
        active = request.POST.get('active') == 'on'

        errors = []
        if not code:
            errors.append(_("Product code is required."))
        elif Product.objects.filter(customer=customer, code=code).exclude(product_id=product_id).exists():
            errors.append(_("A product with this code already exists."))
        if not description:
            errors.append(_("Description is required."))

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
    product_ids = data.get('product_ids', [])

    if not product_ids:
        return JsonResponse({'status': 'error', 'message': _("No products selected.")}, status=400)

    products = Product.objects.filter(customer=customer, product_id__in=product_ids)
    count = products.count()

    if action == 'delete':
        products.delete()
        return JsonResponse({'status': 'ok', 'message': _("{count} product(s) deleted.").format(count=count)})
    elif action == 'activate':
        products.update(active=True)
        return JsonResponse({'status': 'ok', 'message': _("{count} product(s) activated.").format(count=count)})
    elif action == 'deactivate':
        products.update(active=False)
        return JsonResponse({'status': 'ok', 'message': _("{count} product(s) deactivated.").format(count=count)})
    elif action == 'set_location':
        new_location = data.get('value', '').strip()
        products.update(location=new_location)
        return JsonResponse({'status': 'ok', 'message': _("{count} product(s) updated.").format(count=count)})
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

    allowed_fields = ['code', 'description', 'location', 'active']
    if field not in allowed_fields:
        return JsonResponse({'status': 'error', 'message': _("Invalid field.")}, status=400)

    if field == 'active':
        value = value in [True, 'true', '1']
    elif field in ['code', 'description']:
        value = value.strip()
        if not value:
            return JsonResponse({'status': 'error', 'message': _("This field cannot be empty.")}, status=400)
        if field == 'code' and Product.objects.filter(customer=customer, code=value).exclude(product_id=product_id).exists():
            return JsonResponse({'status': 'error', 'message': _("A product with this code already exists.")}, status=400)

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

        if not csv_file.name.endswith('.csv'):
            messages.error(request, _("Please upload a valid CSV file."))
            return render(request, 'manage/products/import.html', context)

        try:
            decoded_file = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(decoded_file))

            created_count = 0
            updated_count = 0
            error_count = 0

            for row in reader:
                code = row.get('code', row.get('Code', '')).strip()
                description = row.get('description', row.get('Description', '')).strip()
                location = row.get('location', row.get('Location', '')).strip()
                active_str = row.get('active', row.get('Active', 'true')).strip().lower()
                active = active_str in ['true', '1', 'yes', 'ja', 'actief']

                if not code or not description:
                    error_count += 1
                    continue

                product, created = Product.objects.update_or_create(
                    customer=customer,
                    code=code,
                    defaults={
                        'description': description,
                        'location': location,
                        'active': active
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            messages.success(request, _("Import completed: {created} created, {updated} updated, {errors} errors.").format(
                created=created_count, updated=updated_count, errors=error_count
            ))
            return redirect('manage_products')

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

@company_admin_required
def orders_list(request):
    """List all orders with search and filter."""
    context = get_base_context(request, 'orders')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    # Get orders
    orders = Order.objects.filter(customer=customer).annotate(
        item_count=Sum('lines__quantity')
    )

    # Search
    search = request.GET.get('search', '').strip()
    if search:
        orders = orders.filter(
            Q(order_code__icontains=search) |
            Q(notes__icontains=search)
        )
        context['search'] = search

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter in ['draft', 'queued', 'in_progress', 'completed', 'cancelled']:
        orders = orders.filter(status=status_filter)
    context['status_filter'] = status_filter

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

    return render(request, 'manage/orders/list.html', context)


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

        if not csv_file.name.endswith('.csv'):
            messages.error(request, _("Please upload a valid CSV file."))
            return render(request, 'manage/orders/import.html', context)

        try:
            decoded_file = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(decoded_file))

            created_count = 0
            line_count = 0
            error_count = 0

            # Group by order_code
            orders_data = {}
            for row in reader:
                order_code = row.get('order_code', row.get('Order Code', '')).strip()
                product_code = row.get('product_code', row.get('Product Code', '')).strip()
                amount = row.get('amount', row.get('Amount', '1')).strip()
                notes = row.get('notes', row.get('Notes', '')).strip()

                if not order_code or not product_code:
                    error_count += 1
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
                    error_count += len(data['lines'])
                    continue

                order = Order.objects.create(
                    customer=customer,
                    order_code=order_code,
                    notes=data['notes'],
                    status='draft'
                )
                created_count += 1

                for line_data in data['lines']:
                    try:
                        product = Product.objects.get(customer=customer, code=line_data['product_code'])
                        OrderLine.objects.create(
                            order=order,
                            product=product,
                            quantity=line_data['amount']
                        )
                        line_count += 1
                    except Product.DoesNotExist:
                        error_count += 1

            messages.success(request, _("Import completed: {orders} orders created with {lines} lines, {errors} errors.").format(
                orders=created_count, lines=line_count, errors=error_count
            ))
            return redirect('manage_orders')

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
    """List all picklists (read-only)."""
    context = get_base_context(request, 'picklists')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    # Get picklists
    picklists = PickList.objects.filter(customer=customer).select_related('device', 'order')

    # Filter by status (using pick_started and successful fields)
    status_filter = request.GET.get('status', '')
    if status_filter == 'pending':
        picklists = picklists.filter(pick_started__isnull=True)
    elif status_filter == 'in_progress':
        picklists = picklists.filter(pick_started=True, successful__isnull=True)
    elif status_filter == 'completed':
        picklists = picklists.filter(successful=True)
    elif status_filter == 'failed':
        picklists = picklists.filter(successful=False)
    context['status_filter'] = status_filter

    # Ordering
    picklists = picklists.order_by('-created_at')

    # Pagination
    paginator = Paginator(picklists, 25)
    page = request.GET.get('page', 1)
    context['picklists'] = paginator.get_page(page)
    context['paginator'] = paginator

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


# ============================================
# Devices (Read-only overview)
# ============================================

@company_admin_required
def devices_list(request):
    """List all devices (read-only)."""
    context = get_base_context(request, 'devices')
    customer = context['customer']

    if not customer:
        return redirect('manage_dashboard')

    # Get devices
    devices = Device.objects.filter(customer=customer).select_related('user')

    # Add activity status
    now = timezone.now()
    for device in devices:
        if device.last_login:
            device.is_active = (now - device.last_login) < timedelta(minutes=15)
        else:
            device.is_active = False

    # Ordering
    devices = devices.order_by('-last_login')

    context['devices'] = devices

    return render(request, 'manage/devices/list.html', context)


# ============================================
# Profile
# ============================================

@company_admin_required
def profile(request):
    """View and edit user profile."""
    context = get_base_context(request, 'profile')
    customer = context['customer']
    user = request.user

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

        return redirect('manage_profile')

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
# Logout
# ============================================

@company_admin_required
def logout_view(request):
    """Log out the current user."""
    logout(request)
    messages.success(request, _("You have been logged out successfully."))
    return redirect('login')

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
import json
from django.views.decorators.http import require_POST
from orderpiqrApp.models import Device, Order, PickList, Product, ProductPick, UserProfile


@require_POST
def scan_picklist(request):
    # Parse JSON
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    picklist = data.get('picklist', [])
    device_fingerprint = data.get('deviceFingerprint', '')
    order_id = data.get('orderID', None)

    # Validate required fields
    if not order_id:
        return JsonResponse({'status': 'error', 'message': 'orderID is required'}, status=400)

    if not device_fingerprint:
        return JsonResponse({'status': 'error', 'message': 'deviceFingerprint is required'}, status=400)

    if not picklist:
        return JsonResponse({'status': 'error', 'message': 'picklist is empty'}, status=400)

    local_time = timezone.localtime(timezone.now())

    # Fetch or create device
    try:
        device = Device.objects.get(device_fingerprint=device_fingerprint)
    except Device.DoesNotExist:
        if not request.user.is_authenticated:
            return JsonResponse({
                'status': 'error',
                'message': 'Device not found and user not authenticated'
            }, status=401)

        try:
            user_profile = UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'User has no customer profile'
            }, status=400)

        device = Device.objects.create(
            user=request.user,
            device_fingerprint=device_fingerprint,
            name=f"Auto-created device ({local_time.strftime('%Y-%m-%d %H:%M')})",
            description=f"Automatically created for user {request.user.username}",
            customer=user_profile.customer,
            last_login=local_time,
            lists_picked=0
        )

    # Process picklist in a transaction
    try:
        with transaction.atomic():
            # Check if there's a queued Order for this order_id
            order = Order.objects.select_for_update().filter(
                order_code=order_id,
                customer=device.customer
            ).first()

            # If order exists and is queued, lock it
            if order:
                if order.status == 'in_progress':
                    return JsonResponse({
                        'status': 'error',
                        'message': 'This order is already being picked by another device'
                    }, status=409)
                elif order.status == 'completed':
                    return JsonResponse({
                        'status': 'error',
                        'message': 'This order has already been completed'
                    }, status=409)
                elif order.status == 'queued':
                    # Lock the order by setting status to in_progress
                    order.status = 'in_progress'
                    order.save(update_fields=['status'])

            try:
                pick_list = PickList.objects.select_for_update().get(
                    picklist_code=order_id,
                    customer=device.customer
                )
                pick_list.device = device
                pick_list.updated_at = local_time
                pick_list.pick_started = True
                new_note = f"Restarted by device {device.name} at {local_time.strftime('%Y-%m-%d %H:%M')}"
                pick_list.notes = (pick_list.notes or "") + "\n" + new_note
                pick_list.save()

                ProductPick.objects.filter(picklist=pick_list).delete()
                created = False

            except PickList.DoesNotExist:
                pick_list = PickList.objects.create(
                    picklist_code=order_id,
                    customer=device.customer,
                    device=device,
                    updated_at=local_time,
                    pick_started=True,
                    order=order  # Link to order if it exists
                )
                created = True

            # Original product handling
            for product_code in picklist:
                product = Product.objects.filter(customer=device.customer, code=product_code).first()
                if not product:
                    raise Product.DoesNotExist()
                ProductPick.objects.create(
                    product=product,
                    picklist=pick_list,
                    quantity=1,
                )

    except Product.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Product not found for one of the product codes'
        }, status=404)
    except IntegrityError as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Database integrity error: {str(e)}'
        }, status=409)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}'
        }, status=500)

    return JsonResponse({
        'status': 'ok',
        'message': 'Picklist processed successfully',
        'created': created,
        'picklist_id': pick_list.picklist_id,
        'product_count': len(picklist)
    })


def product_pick(request):
    payload = json.loads(request.body.decode("utf-8"))
    order_id = payload.get("orderID")
    product_code = payload.get("productCode")
    device_fp = payload.get("deviceFingerprint")
    successful = bool(payload.get("successful", True))
    time_taken_ms = payload.get("timeTakenMs")
    scanned_at = payload.get("scannedAt") or timezone.now().isoformat()

    try:
        device = Device.objects.get(device_fingerprint=device_fp)
    except Device.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Device not found with given fingerprint"}, status=404)

    picklist = (PickList.objects.filter(picklist_code=order_id, customer=device.customer, device=device)
                .select_related("customer", "device")
                .first())
    if not picklist:
        return JsonResponse({"status": "error", "message": "PickList not found for device/customer"}, status=404)

    try:
        product = Product.objects.filter(customer=device.customer, code=product_code).first()
        if not product:
            raise Product.DoesNotExist()
    except Product.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Product not found"}, status=404)

    # Find the next unpicked row for this product in this picklist
    qs = ProductPick.objects.filter(picklist=picklist, product=product).order_by("id")
    pp = qs.filter(successful__isnull=True).first() or qs.filter(successful=False).first()
    if not pp:
        # Idempotent: nothing left to update for this product
        return JsonResponse({"status": "noop", "message": "No pending ProductPick rows for this product."},
                            status=200, )

    time_taken = timedelta(milliseconds=int(time_taken_ms))

    # Update fields
    pp.successful = successful
    pp.time_taken = time_taken

    # Append device/scanned info to notes
    stamp = f"device={device_fp}; scanned_at={scanned_at}"
    pp.notes = f"{pp.notes}\n{stamp}" if pp.notes else stamp

    pp.save(update_fields=["successful", "time_taken", "notes"])

    remaining_for_product = qs.filter(successful__isnull=True).count()

    return JsonResponse(
        {
            "status": "ok",
            "picklist_code": picklist.picklist_code,
            "product_code": product.code,
            "updated_productpick_id": pp.id,
            "remaining_for_product": remaining_for_product,
        },
        status=200,
    )


def complete_picklist(request):
    if request.method == 'POST':
        try:
            # Parse the incoming JSON request
            data = json.loads(request.body)
            device_fingerprint = data.get('deviceFingerprint', '')
            order_id = data.get('orderID', None)  # Assuming orderID is passed in the request
            # Fetch the device using the fingerprint
            device = Device.objects.get(device_fingerprint=device_fingerprint)
            picklist = PickList.objects.filter(picklist_code=order_id, customer=device.customer,
                                               device=device).first()
            if picklist:
                now = timezone.localtime(timezone.now())  # now in local time
                pick_time = timezone.localtime(picklist.pick_time)  # ensure pick_time is also local
                picklist.time_taken = now - pick_time
                picklist.successful = True  # or set based on some logic
                picklist.save()

                # Mark the linked order as completed if it exists
                if picklist.order:
                    picklist.order.status = 'completed'
                    picklist.order.completed_at = now
                    picklist.order.save(update_fields=['status', 'completed_at'])
            else:
                print('No picklist found, contact support')

            return JsonResponse({'status': 'ok', 'message': 'Picklist processed successfully'})

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Device not found with given fingerprint'}, status=404)
        except Product.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Product not found for one of the product codes'},
                                status=404)
        except Exception as e:

            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

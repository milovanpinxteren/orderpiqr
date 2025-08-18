from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
import json

from orderpiqrApp.models import Device, PickList, Product, ProductPick


def scan_picklist(request):
    if request.method == 'POST':
        try:
            # Parse the incoming JSON request
            data = json.loads(request.body)
            picklist = data.get('picklist', [])
            device_fingerprint = data.get('deviceFingerprint', '')
            order_id = data.get('orderID', None)  # Assuming orderID is passed in the request

            # Fetch the device using the fingerprint
            device = Device.objects.get(device_fingerprint=device_fingerprint)
            local_time = timezone.localtime(timezone.now())

            pick_list, created = PickList.objects.update_or_create(
                picklist_code=order_id,
                customer=device.customer,
                defaults={
                    'device': device,
                    'updated_at': local_time,
                    'pick_started': True
                }
            )
            if not created:  # if overwritten
                new_note = f"Added by device {device.name} at {local_time.strftime("%Y-%m-%d %H:%M")}"
                pick_list.notes = (pick_list.notes or "") + "\n" + new_note
                pick_list.save()
                ProductPick.objects.filter(picklist=pick_list).delete()
            # Loop through each product in the picklist and create ProductPick entries
            for product_code in picklist:
                product = Product.objects.get(customer=device.customer, code=product_code)
                ProductPick.objects.create(
                    product=product,
                    picklist=pick_list,
                    quantity=1,
                )

            # Return a success response with details
            return JsonResponse({'status': 'ok', 'message': 'Picklist processed successfully'})

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Device not found with given fingerprint'}, status=404)
        except Product.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Product not found for one of the product codes'},
                                status=404)
        except Exception as e:

            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)



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
        product = Product.objects.get(code=product_code)
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

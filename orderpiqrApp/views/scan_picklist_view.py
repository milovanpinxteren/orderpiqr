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

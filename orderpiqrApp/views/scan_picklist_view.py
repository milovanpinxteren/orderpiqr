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

            pick_list, created = PickList.objects.update_or_create(
                picklist_code=order_id,
                customer=device.customer,
                defaults={
                    'device': device,
                    'updated_at': timezone.now(),
                }
            )
            # Optional: only set created_at if it's a new object
            if created:
                pick_list.created_at = timezone.now()
                pick_list.save()

            # Loop through each product in the picklist and create ProductPick entries
            for product_code in picklist:
                # Retrieve the Product based on the product code
                product = Product.objects.get(customer=device.customer, code=product_code)

                # Create a ProductPick entry for each product in the picklist
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

            pick_list = PickList.objects.get(
                picklist_code=order_id,
                customer=device.customer,
                device=device,
            )
            pick_list.successful = True
            pick_list.updated_at = timezone.now()
            pick_list.save()

            return JsonResponse({'status': 'ok', 'message': 'Picklist processed successfully'})

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Device not found with given fingerprint'}, status=404)
        except Product.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Product not found for one of the product codes'},
                                status=404)
        except Exception as e:

            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

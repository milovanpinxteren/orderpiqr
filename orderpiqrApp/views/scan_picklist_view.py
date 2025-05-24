from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json

from orderpiqrApp.models import Device, PickList, Product, ProductPick


@csrf_exempt  # Temporarily exempt CSRF for simplicity (you can later make this more secure)
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

            pick_list = PickList.objects.create(
                picklist_code=order_id,
                customer=device.customer,
                device=device,
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )

            # Loop through each product in the picklist and create ProductPick entries
            for product_code in picklist:
                # Retrieve the Product based on the product code
                product = Product.objects.get(customer=device.customer,code=product_code)

                # Create a ProductPick entry for each product in the picklist
                ProductPick.objects.create(
                    product=product,
                    picklist=pick_list,
                    quantity=1,
                )

            # Return a success response with details
            return JsonResponse({'status': 'success', 'message': 'Picklist processed successfully'})

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Device not found with given fingerprint'}, status=404)
        except Product.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Product not found for one of the product codes'}, status=404)
        except Exception as e:

            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

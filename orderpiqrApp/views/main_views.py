from django.shortcuts import render

from orderpiqrApp.models import Product, Device


def index(request):
    print('index main view')
    device_fingerprint = request.session.get('device_fingerprint')
    # device = Device.objects.first()
    device = Device.objects.filter(user=request.user, device_fingerprint=device_fingerprint).first()
    product_data = Product.objects.filter(active=True, customer=request.user.userprofile.customer)
    product_data = product_data.values('product_id', 'code', 'description', 'location')
    context = {'product_data': str(list(product_data)).replace("'", '"'), 'username': device.name}
    return render(request, 'index.html', context)
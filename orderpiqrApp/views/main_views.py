from django.shortcuts import render

from orderpiqrApp.models import Product


def index(request):
    print('index main view')
    product_data = Product.objects.filter(active=True, customer=request.user.userprofile.customer)
    product_data = product_data.values('product_id', 'code', 'description', 'location')
    context = {'product_data': str(list(product_data)).replace("'", '"')}  # Convert QuerySet to list of dictionaries
    return render(request, 'index.html', context)
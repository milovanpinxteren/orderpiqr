from django.shortcuts import render


def index(request):
    print('index mian view')
    context = {}
    return render(request, 'index.html', context)
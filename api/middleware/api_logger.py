import json
from api.models import APIRequestLog

class APILoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.path.startswith('/api/'):
            user = request.user if request.user.is_authenticated else None
            method = request.method
            path = request.path

            APIRequestLog.objects.create(
                user=user,
                method=method,
                path=path,
                status_code=response.status_code,
            )

        return response

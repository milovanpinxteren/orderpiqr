from django.db import models
from django.contrib.auth.models import User

class APIRequestLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)
    payload = models.JSONField(null=True, blank=True)
    status_code = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.method} {self.path} ({self.status_code}) by {self.user}"

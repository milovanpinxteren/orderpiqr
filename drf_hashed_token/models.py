import hashlib
import secrets

from django.conf import settings
from django.db import models


class HashedToken(models.Model):
    class TokenStage(models.TextChoices):
        LIVE = "LIVE", "Live"
        TEST = "TEST", "Test"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='drf_hashed_token', on_delete=models.CASCADE)
    key_hash = models.CharField("Token Hash", max_length=64, primary_key=True, editable=False)
    stage = models.CharField(max_length=4, choices=TokenStage.choices, default=TokenStage.TEST)
    created = models.DateTimeField(auto_now_add=True)

    _raw_token = None

    class Meta:
        unique_together = [['user', 'stage'],]
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"

    def __str__(self):
        return f"{self.get_stage_display()} token for {self.user}"

    @classmethod
    def generate_token(cls):
        raw_token = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return raw_token, key_hash

    def check_token(self, raw_token: str) -> bool:
        return self.key_hash == hashlib.sha256(raw_token.encode()).hexdigest()

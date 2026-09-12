import hashlib

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.plumbing import build_bearer_security_scheme_object
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import HashedToken


class TokenScheme(OpenApiAuthenticationExtension):
    target_class = 'drf_hashed_token.authentication.HashedTokenAuthentication'
    name = 'tokenAuth'
    match_subclasses = True
    priority = -1

    def get_security_definition(self, auto_schema):
        return build_bearer_security_scheme_object(
            header_name='Authorization',
            token_prefix=self.target.keyword,
        )


class HashedTokenAuthentication(TokenAuthentication):
    model = HashedToken
    keyword = 'Token'

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user = result[0]
            request._request.user = user

            async def _return_user():
                return user
            request._request.auser = _return_user
        return result

    def authenticate_credentials(self, fullkey):
        keyparts = fullkey.split('_', 1)
        stage = keyparts[0].upper()
        if stage in HashedToken.TokenStage.values:
            token_prefix = getattr(settings, 'TOKEN_PREFIX', 'LIVE').upper()
            if stage != HashedToken.TokenStage(token_prefix):
                msg = _("Invalid token. Only tokens prefixed with '%(stage)s_' are accepted.") % {
                    'stage': HashedToken.TokenStage(token_prefix).label}
                raise AuthenticationFailed(msg)
            else:
                key = keyparts[1]
        else:
            raise AuthenticationFailed(_('Invalid token prefix.'))
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        try:
            token = self.model.objects.select_related('user').get(key_hash=key_hash, stage__iexact=stage)
        except self.model.DoesNotExist:
            raise AuthenticationFailed(_('Invalid token.'))
        if not token.user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))
        return (token.user, token)

"""Rate limiting for machine-to-machine API traffic."""
from rest_framework.throttling import SimpleRateThrottle

from drf_hashed_token.models import HashedToken


class HashedTokenRateThrottle(SimpleRateThrottle):
    """Per-token rate limit for requests authenticated with a hashed API
    token (portal integrations). Interactive JWT/session traffic is not
    throttled here."""

    scope = 'hashed_token'

    def get_cache_key(self, request, view):
        if not isinstance(request.auth, HashedToken):
            return None  # only token-authenticated requests are throttled
        return self.cache_format % {
            'scope': self.scope,
            'ident': request.auth.key_hash,
        }

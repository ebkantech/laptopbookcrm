from rest_framework.throttling import SimpleRateThrottle


class LoginRateThrottle(SimpleRateThrottle):
    """
    Brute-force protection scoped to the login endpoint only. Keyed by
    IP address (not by user, since a failed login has no authenticated
    user yet) so repeated password-guessing from one source gets
    rate-limited regardless of which username is being tried.
    """
    scope = "login"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}

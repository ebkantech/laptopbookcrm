from rest_framework.throttling import SimpleRateThrottle


class CustomerLoginRateThrottle(SimpleRateThrottle):
    scope = "customer_login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class CustomerTokenRateThrottle(SimpleRateThrottle):
    scope = "customer_token"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}

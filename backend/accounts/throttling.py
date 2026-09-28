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


class OTPVerifyThrottle(SimpleRateThrottle):
    """
    Task 6 security checklist: "OTP verification endpoint throttled
    (prevents brute-forcing a customer's OTP)". A 4-digit/6-digit OTP is
    guessable in a handful of tries without this -- keyed by IP for the
    same reason as LoginRateThrottle (no authenticated identity exists
    yet at this point in the portal login flow).
    """
    scope = "otp_verify"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}

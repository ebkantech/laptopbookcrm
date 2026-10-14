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


class OTPResendThrottle(SimpleRateThrottle):
    """Per-IP cap on portal "send me a new code" requests (each one sends an email)."""
    scope = "otp_resend"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OTPResendInviteThrottle(SimpleRateThrottle):
    """
    Per-invitation cap on resends, keyed by the link token, so one
    customer's inbox can't be flooded from many IPs. The short per-code
    cooldown (PORTAL_OTP_RESEND_COOLDOWN_SECONDS) is enforced separately
    in portal.services.resend_otp.
    """
    scope = "otp_resend_invite"

    def get_cache_key(self, request, view):
        token = str(request.data.get("token") or "").strip().lower()[:64]
        if not token:
            return None
        return self.cache_format % {"scope": self.scope, "ident": token}


class PortalPdfThrottle(SimpleRateThrottle):
    """Caps invoice-PDF generation per signed-in portal customer (each one renders a PDF server-side)."""
    scope = "portal_pdf"

    def get_cache_key(self, request, view):
        party = getattr(request, "party", None)
        ident = f"party-{party.pk}" if party else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}

"""
Sign-in security: the login audit (LoginAttempt), the per-account lockout,
and the cap on how long one sign-in can be kept alive by token refreshes.

  - Every attempt is recorded: failures through Django's user_login_failed
    signal (fired by authenticate() for the API login and the admin login
    alike), successes by the login view / user_logged_in.
  - LOGIN_MAX_FAILURES failures for one username inside
    LOGIN_FAILURE_WINDOW_MINUTES lock that username until the window moves
    on -- whichever addresses they came from. The per-address throttle
    (accounts.throttling.LoginRateThrottle) still applies on top.
  - Refresh tokens carry the time of the original sign-in ("auth_time");
    rotation keeps it, and a refresh older than JWT_MAX_SESSION_DAYS is refused.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.exceptions import Throttled
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger("accounts.security")


def client_ip(request):
    """The caller's address, read the same proxy-aware way the rate limits read it."""
    if request is None:
        return None
    from .throttling import LoginRateThrottle

    ip = (LoginRateThrottle().get_ident(request) or "").strip()
    return ip[:45] or None


def _window_start():
    return timezone.now() - timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)


def is_locked(username):
    from .models import LoginAttempt

    username = (username or "").strip()
    if not username:
        return False
    failures = LoginAttempt.objects.filter(username__iexact=username, success=False, reason="bad password",
                                           at__gte=_window_start()).count()
    return failures >= settings.LOGIN_MAX_FAILURES


def record(username, success, request=None, user=None, reason="", via="api"):
    from .models import LoginAttempt

    try:
        LoginAttempt.objects.create(username=(username or "")[:150], user=user, success=success, reason=reason[:40],
                                    ip=client_ip(request), via=via)
    except Exception:  # an audit write must never break signing in
        logger.exception("could not record a login attempt")
    if not success and reason == "bad password" and is_locked(username):
        logger.warning("account %r locked after repeated failed sign-ins (last from %s)", username, client_ip(request))


def _via(request):
    path = getattr(request, "path", "") or ""
    return "admin" if path.startswith("/" + settings.ADMIN_URL) else "api"


@receiver(user_login_failed)
def _on_failed(sender, credentials, request=None, **kwargs):
    record(credentials.get("username"), False, request, reason="bad password", via=_via(request))


@receiver(user_logged_in)
def _on_admin_login(sender, request, user, **kwargs):
    # the API login never calls login(); this is the Django admin
    record(user.get_username(), True, request, user=user, via="admin")


class StaffTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Staff sign-in: locked-out usernames are refused before the password is
    even checked; customer identities never get staff tokens."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["auth_time"] = int(timezone.now().timestamp())
        return token

    def validate(self, attrs):
        request = self.context.get("request")
        username = attrs.get(self.username_field)
        if is_locked(username):
            record(username, False, request, reason="locked")
            raise Throttled(detail=f"Too many failed sign-ins for this account. Try again in "
                                   f"{settings.LOGIN_FAILURE_WINDOW_MINUTES} minutes, or ask an administrator to reset the password.")
        data = super().validate(attrs)  # a wrong password fires user_login_failed -> recorded
        if hasattr(self.user, "customer_profile"):
            record(username, False, request, user=self.user, reason="not staff")
            raise AuthenticationFailed("Invalid username or password")
        record(username, True, request, user=self.user)
        return data


class CappedTokenRefreshSerializer(TokenRefreshSerializer):
    """Refuses to refresh a sign-in older than JWT_MAX_SESSION_DAYS."""

    def validate(self, attrs):
        token = RefreshToken(attrs["refresh"])
        started = token.payload.get("auth_time") or token.payload.get("iat")
        if started and timezone.now().timestamp() - int(started) > settings.JWT_MAX_SESSION_DAYS * 86400:
            raise InvalidToken("This sign-in has expired. Please sign in again.")
        return super().validate(attrs)

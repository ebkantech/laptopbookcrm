from django.conf import settings
from django.http import HttpResponse


class AdminLoginThrottleMiddleware:
    """
    The Django admin's login form is a second way to try passwords. Give it
    the same per-address limit as the API login (LOGIN_THROTTLE_RATE) and the
    same per-account lockout (accounts.auth.is_locked).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == f"/{settings.ADMIN_URL}login/":
            from .auth import is_locked, record
            from .throttling import LoginRateThrottle

            username = request.POST.get("username", "")
            if is_locked(username):
                record(username, False, request, reason="locked", via="admin")
                return HttpResponse("Too many failed sign-ins for this account. Try again later.", status=429, content_type="text/plain")
            if not LoginRateThrottle().allow_request(request, None):
                return HttpResponse("Too many sign-in attempts. Try again in a minute.", status=429, content_type="text/plain")
        return self.get_response(request)

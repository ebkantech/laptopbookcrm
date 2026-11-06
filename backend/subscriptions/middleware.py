"""
The access block. It works on the URL before any view runs, so it covers every
route, public approval pages and AI-Staff (whose calls come through here too).
"""
from django.http import JsonResponse

from . import catalog, services

READ_METHODS = ("GET", "HEAD", "OPTIONS")
# Signing in, changing a password and seeing the plan must work while read-only,
# and a provider's webhook reports money or delivery that has already happened.
ALWAYS_WRITABLE = ("/api/auth/", "/api/users/me/", "/api/subscription/")


class SubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not path.startswith("/api/") or "webhook" in path:
            return self.get_response(request)
        module = services.blocked_module(path)
        if module:
            return JsonResponse({
                "detail": f"{catalog.label(module)} isn't in your subscription.", "code": "module_not_in_plan",
            }, status=403)
        if (request.method not in READ_METHODS and not path.startswith(ALWAYS_WRITABLE)
                and services.state() == services.READ_ONLY):
            return JsonResponse({
                "detail": "Your subscription has ended, so the CRM is read-only. Renew to make changes.",
                "code": "subscription_read_only",
            }, status=403)
        return self.get_response(request)

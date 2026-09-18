from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.utils import timezone

from .models import CustomerProfile


class CustomerPortalSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/customer/") and request.user.is_authenticated:
            try:
                request.user.customer_profile
            except CustomerProfile.DoesNotExist:
                pass
            else:
                now = timezone.now().timestamp()
                authenticated_at = request.session.get("customer_authenticated_at", now)
                last_activity = request.session.get("customer_last_activity", now)
                idle_seconds = int(getattr(settings, "CUSTOMER_PORTAL_IDLE_SECONDS", 1800))
                absolute_seconds = int(getattr(settings, "CUSTOMER_PORTAL_SESSION_SECONDS", 28800))
                if now - last_activity > idle_seconds or now - authenticated_at > absolute_seconds:
                    logout(request)
                    return JsonResponse({"detail": "Your customer session expired. Please sign in again."}, status=401)
                request.session["customer_last_activity"] = now
        return self.get_response(request)

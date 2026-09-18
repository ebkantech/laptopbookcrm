from rest_framework.permissions import BasePermission

from .models import CustomerProfile


class IsActiveCustomer(BasePermission):
    message = "Customer portal authentication is required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            profile = request.user.customer_profile
        except CustomerProfile.DoesNotExist:
            return False
        return profile.status == CustomerProfile.ACTIVE

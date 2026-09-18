from rest_framework.permissions import BasePermission

SAFE_ACTIONS = {"list", "retrieve"}


class IsStaffAccount(BasePermission):
    """Keep portal customer identities out of internal CRM endpoints."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser or not hasattr(request.user, "customer_profile")


class HasPerm(BasePermission):
    """
    DRF permission class driven by the same object-based permission
    codes the frontend already knows about (see PERMS in the
    prototype). Attach `required_perm = "cashbook.edit"` (a string) or
    `required_perms = {"list": "cashbook.view", "create": "cashbook.edit"}`
    (per-action) on the ViewSet.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if hasattr(request.user, "customer_profile"):
            return False
        if request.user.is_superuser:
            return True

        per_action = getattr(view, "required_perms", None)
        if per_action:
            codename = per_action.get(view.action)
            if codename is None:
                return True
            return request.user.has_perm_code(codename)

        codename = getattr(view, "required_perm", None)
        if codename is None:
            return True
        return request.user.has_perm_code(codename)

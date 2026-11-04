"""
Active role and active store -- the two per-request contexts a staff
account works in, chosen in the CRM (Dashboard role switcher, sidebar
store switcher) and sent on every API request as headers:

  X-Active-Role:  id of one of the account's assigned roles
  X-Active-Store: id of a store the account may reach, or "all"

Neither is ever trusted. Right after the existing JWT / session
authentication identifies the account, apply_context() checks each one
against the account's own assignments in the database (User.roles /
User.stock_points, plus the primary role / store) and refuses anything
else with 403 -- so a hand-edited request can't borrow a role or reach a
store the account doesn't hold. Without the headers the account works as
before: primary role, and the Owner sees every store / staff their primary
store.

The chosen role replaces the account's role for that request only, so
every existing check (HasPerm, has_perm_code, sees_all_stores, the
dashboard sections, the role-grant rules) follows it unchanged; User.save
never persists it. A superuser holds every permission whatever role is
chosen. The chosen store narrows accounts.store_scope.StoreScope -- the
store filter every store-linked module already goes through.
"""
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

ROLE_HEADER = "HTTP_X_ACTIVE_ROLE"
STORE_HEADER = "HTTP_X_ACTIVE_STORE"
ALL_STORES = "all"


class ContextRefused(PermissionDenied):
    def __init__(self, detail, code):
        super().__init__({"detail": detail, "code": code})


def apply_context(request, user):
    """Validate and apply the requested role, then the requested store (the
    role decides whether the account is the Owner, i.e. may pick any store)."""
    if getattr(user, "_context_applied", False):
        return
    user._context_applied = True
    role_value = (request.META.get(ROLE_HEADER) or "").strip()
    store_value = (request.META.get(STORE_HEADER) or "").strip()
    if role_value and not user.is_superuser:
        _apply_role(user, role_value)
    if store_value:
        _apply_store(user, store_value)


def _apply_role(user, value):
    from .models import Role

    try:
        role_id = int(value)
    except ValueError:
        role_id = None
    if role_id is None or role_id not in user.assigned_role_ids():
        raise ContextRefused("That role isn't assigned to your account.", "invalid_active_role")
    if role_id != user.role_id:
        user._primary_role_id = user.role_id  # User.save writes this back, never the switch
        user.role = Role.objects.get(pk=role_id)


def _apply_store(user, value):
    from .store_scope import sees_all_stores

    owner = sees_all_stores(user)
    if value == ALL_STORES:
        if not owner:
            raise ContextRefused("All Stores is only available to the Owner.", "invalid_active_store")
        user._active_store_id = None
        return
    try:
        store_id = int(value)
    except ValueError:
        store_id = None
    if store_id is None or not _reachable(user, store_id, owner):
        raise ContextRefused("You don't have access to that store.", "invalid_active_store")
    user._active_store_id = store_id


def _reachable(user, store_id, owner):
    from catalog.models import StockPoint

    if owner:
        return StockPoint.objects.filter(pk=store_id).exists()
    return store_id in user.assigned_store_ids()


def context_payload(user):
    """The switchers' choices and current values for GET /users/me/: only the
    account's own roles and reachable stores (physical shops; for the Owner,
    every shop -- online channels are sales channels, not branches)."""
    from catalog.models import StockPoint

    from .models import Role
    from .store_scope import StoreScope

    scope = StoreScope(user)
    if scope.owner:
        stores = StockPoint.objects.filter(kind=StockPoint.SHOP)
    else:
        stores = StockPoint.objects.filter(pk__in=user.assigned_store_ids())
    roles = [] if user.is_superuser else Role.objects.filter(pk__in=user.assigned_role_ids())
    return {
        "assigned_roles": [{"id": r.id, "slug": r.slug, "label": r.label} for r in roles],
        "active_role": None if user.is_superuser else user.role_id,
        "accessible_stores": [
            {"id": s.id, "name": s.name, "kind": s.kind, "is_active": s.is_active} for s in stores.order_by("name")
        ],
        "can_select_all_stores": scope.owner,
        "active_store": scope.store_id,
    }


class ContextJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            apply_context(request, result[0])
        return result


class ContextSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            apply_context(request, result[0])
        return result

"""
Store-level data isolation, layered on top of the role permissions in
accounts.permissions.

Two separate questions are asked of every request:
  1. HasPerm -- may this role use the module/action at all? (unchanged)
  2. StoreScope -- which stock point's records may this account reach?

Only the Owner / Super Admin sees every store: a superuser, or the
built-in "owner" role (which can't be created, edited or handed out
through the API -- see RoleWriteSerializer and UserViewSet.set_role).
Everyone else is limited to User.stock_point, which only the Owner can
set. An account with no assignment reaches no store's records at all --
it never falls back to "everything".

A store is never taken from the request: querysets are filtered by the
account's own assignment, and a stock point named in a write payload is
checked against it.
"""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

OWNER_ROLE_SLUG = "owner"
PENDING_DETAIL = "Your Store Location has not been assigned yet. Please contact your administrator."


def sees_all_stores(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = getattr(user, "role", None)
    return bool(role and role.slug == OWNER_ROLE_SLUG)


class StoreScope:
    """The stock points one user may reach. `store_id` is None for the Owner (all stores)."""

    def __init__(self, user):
        self.user = user
        self.all = sees_all_stores(user)
        self.store_id = None if self.all else getattr(user, "stock_point_id", None)

    @property
    def assigned(self):
        return self.all or self.store_id is not None

    def q(self, *lookups):
        """Q matching rows whose store (via any of `lookups`) is this user's store."""
        if not lookups:
            raise ValueError("StoreScope.q() needs at least one lookup")
        q = Q()
        for lookup in lookups:
            q |= Q(**{lookup: self.store_id})
        return q

    def filter(self, qs, *lookups, distinct=False):
        """Limit `qs` to this user's store. Pass more than one lookup to OR them
        (e.g. a rental asset taken from OR returned to the store)."""
        if self.all:
            return qs
        if self.store_id is None:
            return qs.none()
        qs = qs.filter(self.q(*lookups))
        return qs.distinct() if distinct else qs

    def allows(self, stock_point_id):
        if self.all:
            return True
        if self.store_id is None or stock_point_id in (None, ""):
            return False
        try:
            return int(stock_point_id) == self.store_id
        except (TypeError, ValueError):
            return False

    def require_assigned(self):
        if not self.assigned:
            raise PermissionDenied(PENDING_DETAIL)

    def require(self, stock_point_id, what="this"):
        """Refuse a write naming a stock point outside this user's store."""
        self.require_assigned()
        if not self.allows(stock_point_id):
            raise PermissionDenied(f"You can only work with {what} at your assigned store.")

    def require_owner(self, detail):
        if not self.all:
            raise PermissionDenied(detail)


def _payload_value(data, field):
    if not hasattr(data, "get") or field not in data:
        return None, False
    value = data.get(field)
    if isinstance(value, dict):
        value = value.get("id")
    return value, True


class StoreScopedMixin:
    """
    For a ModelViewSet whose rows belong to a store through `store_lookups`
    (ORed). Every list / retrieve / update / destroy / custom detail action
    goes through get_queryset(), so a record at another store is a 404.
    `store_payload_field`, when set, is the writable stock-point field: a
    create or update naming any other store is refused before the
    serializer runs, so it can't be used to move a record between stores.
    """
    store_lookups = ("stock_point",)
    store_payload_field = "stock_point"
    store_distinct = False

    @property
    def store_scope(self):
        if not hasattr(self, "_store_scope"):
            self._store_scope = StoreScope(self.request.user)
        return self._store_scope

    def get_queryset(self):
        return self.store_scope.filter(super().get_queryset(), *self.store_lookups, distinct=self.store_distinct)

    def check_store_payload(self, request, required=False):
        if not self.store_payload_field:
            return
        value, present = _payload_value(request.data, self.store_payload_field)
        if present or required:
            self.store_scope.require(value, "records")

    def create(self, request, *args, **kwargs):
        self.store_scope.require_assigned()
        self.check_store_payload(request)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self.check_store_payload(request)
        return super().update(request, *args, **kwargs)

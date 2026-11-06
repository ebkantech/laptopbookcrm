from django.conf import settings
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from catalog.models import StockPoint
from catalog.status import require_active
from crmbook_backend.notify import send_email

from .context import context_payload
from .models import NotificationRule, Permission, Role, StaffNotification, User
from subscriptions import services as subscription_services

from .permissions import HasPerm, IsStaffAccount
from .staff import (
    SETUP_LINK_HOURS, STAFF_ADMIN_PERM, check_can_manage, check_outsource, check_role_grant, deletable_with_user,
    email_delivery_configured, is_last_owner, log_admin_action, revoke_sessions, setup_link, setup_tokens,
)
from .store_scope import StoreScope, sees_all_stores
from .serializers import (
    ChangePasswordSerializer, NotificationRuleSerializer, PermissionSerializer, RoleSerializer, RoleWriteSerializer,
    SetPasswordSerializer, StaffNotificationSerializer, StaffWriteSerializer, UserSerializer,
)
from .throttling import LoginRateThrottle, PasswordChangeThrottle


@require_GET
@ensure_csrf_cookie
def csrf_cookie(request):
    """Set Django's CSRF cookie for clients using SessionAuthentication."""
    return JsonResponse({"detail": "CSRF cookie set."})


from .auth import StaffTokenObtainPairSerializer  # noqa: E402  (lockout + audit + session cap live in accounts.auth)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Same as SimpleJWT's login view, with brute-force rate limiting applied."""
    serializer_class = StaffTokenObtainPairSerializer
    throttle_classes = [LoginRateThrottle]


class LogoutView(APIView):
    """
    Blacklists the refresh token on explicit sign-out, so a token that
    leaked (or was left in browser storage on a shared machine) can't
    be exchanged for a fresh access token after the user has logged
    out -- it's dead immediately, not just eventually expired.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": "refresh token is required"}, status=400)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response({"detail": "Token is invalid or already blacklisted"}, status=400)
        return Response(status=205)


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated, IsStaffAccount]


class RoleViewSet(viewsets.ModelViewSet):
    """
    Task 1: the "Roles & access" screen's own read/write API. List and
    retrieve stay open to any signed-in staff account -- that's what
    renders the permission matrix everyone sees. Creating a role,
    changing which permissions it holds, or deleting it are gated on
    roles.manage, same as assigning a role to a user (UserViewSet.set_role
    below). The built-in "owner" role can't be created, edited, or
    deleted through this API -- see RoleWriteSerializer and destroy().
    """
    queryset = Role.objects.prefetch_related("permissions").all()
    permission_classes = [IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "apps": None,
        "create": "roles.manage", "update": "roles.manage",
        "partial_update": "roles.manage", "destroy": "roles.manage",
    }

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return RoleWriteSerializer
        return RoleSerializer

    @action(detail=False, methods=["get"])
    def apps(self, request):
        """The apps and which permissions belong to each (for the access screen)."""
        from .app_catalog import catalog

        return Response(catalog(Permission.objects.values_list("codename", flat=True)))

    def _check_no_escalation(self, request, role, new_codes):
        """An Admin hands out only what they hold themselves; the Owner /
        Super Admin can grant anything."""
        if request.user.is_superuser or new_codes is None:
            return
        mine = set(request.user.role.permissions.values_list("codename", flat=True)) if request.user.role_id else set()
        before = set(role.permissions.values_list("codename", flat=True)) if role else set()
        known = set(Permission.objects.filter(codename__in=new_codes).values_list("codename", flat=True))  # unknown codes are rejected (400) when saving
        changed = (known ^ before) if not set(new_codes) - known else set()
        beyond = sorted(changed - mine)
        if beyond:
            raise PermissionDenied(f"You can only grant or remove access you hold yourself. Not allowed: {', '.join(beyond)}.")

    def create(self, request, *args, **kwargs):
        writer = self.get_serializer(data=request.data)
        writer.is_valid(raise_exception=True)
        self._check_no_escalation(request, None, request.data.get("permission_codes") or [])
        role = writer.save()
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        writer = self.get_serializer(instance, data=request.data, partial=partial)
        writer.is_valid(raise_exception=True)
        self._check_no_escalation(request, instance, request.data.get("permission_codes"))
        role = writer.save()
        return Response(RoleSerializer(role).data)

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()
        if role.slug == "owner":
            return Response({"detail": "The Owner role can't be deleted -- it's tied to the superuser account itself."}, status=400)
        in_use = role.users.count()
        if in_use:
            return Response(
                {"detail": f"{in_use} team member{'s' if in_use != 1 else ''} still {'have' if in_use != 1 else 'has'} this role -- reassign them first."},
                status=400,
            )
        role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationRuleViewSet(viewsets.ModelViewSet):
    """
    Task 2: the Settings > Staff alerts screen. Fully gated on
    roles.manage (list included) -- unlike RoleViewSet, this isn't
    something every signed-in account needs to see, it's an admin
    config surface. See crmbook_backend.notify.notify_staff for how
    these rows are actually used.
    """
    queryset = NotificationRule.objects.select_related("role").all()
    serializer_class = NotificationRuleSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "roles.manage"

    @action(detail=False, methods=["get"])
    def events(self, request):
        return Response([{"key": key, "label": label} for key, label in NotificationRule.EVENT_CHOICES])


class StaffNotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The header bell's own inbox -- always scoped to the requesting
    user (there's no "view someone else's notifications", so no
    roles.manage gate is needed here the way NotificationRuleViewSet
    has one). Written by crmbook_backend.notify.notify_staff(), read
    here, and marked read here.
    """
    serializer_class = StaffNotificationSerializer
    permission_classes = [IsAuthenticated, IsStaffAccount]

    def get_queryset(self):
        return StaffNotification.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        # Capped at 50 -- this is a quick dropdown, not a full inbox
        # page, so there's no pagination UI to page through more.
        qs = self.get_queryset()[:50]
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(read_at__isnull=True).count()})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        if not notif.read_at:
            notif.read_at = timezone.now()
            notif.save(update_fields=["read_at"])
        return Response(StaffNotificationSerializer(notif).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"status": "ok"})


class UserViewSet(viewsets.ModelViewSet):
    """
    Staff directory and Staff Management (Settings).

    Reads: the Owner sees the whole team, store staff their own store's
    team, unassigned staff only themselves (colleagues' email / phone are
    hidden from non-administrators -- UserSerializer.to_representation).

    Writes are for staff administrators (roles.manage, or the Owner) and
    stay inside their reach: get_object() only finds accounts in their
    scope, accounts.staff.check_can_manage() keeps Owner / superuser
    accounts and the administrator's own account out of it, and
    check_role_grant() refuses any role carrying a permission the
    administrator doesn't hold. Store Location stays Owner-only (set_store);
    a store administrator's new staff are always created at their store.
    Deleting is Owner-only and only for accounts with no history --
    everyone else is deactivated (is_active) instead.
    """
    queryset = User.objects.select_related("role", "stock_point").prefetch_related("roles", "stock_points").all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    required_perms = {
        "list": None, "retrieve": None, "me": None,
        # self-service -- always the requesting account
        "change_password": None,
        "set_role": STAFF_ADMIN_PERM,
        "create": STAFF_ADMIN_PERM, "partial_update": STAFF_ADMIN_PERM,
        "set_active": STAFF_ADMIN_PERM, "reset_password": STAFF_ADMIN_PERM,
        # Owner-only -- checked inside, since no role codename (not even
        # roles.manage) may hand out store access or delete accounts.
        "set_store": None, "destroy": STAFF_ADMIN_PERM,
        # Superuser / administrators only -- checked inside (accounts.activity)
        "activity": None,
    }

    def get_queryset(self):
        # Owner: the whole team. Store staff: their own store's team (plus
        # themselves). Unassigned: only themselves.
        qs = super().get_queryset()
        scope = StoreScope(self.request.user)
        if scope.all:
            return qs
        if scope.store_id is None:
            return qs.filter(pk=self.request.user.pk)
        # a store's team (primary or additional store), plus the field /
        # outsourced technicians who belong to no store
        return qs.filter(Q(stock_point_id=scope.store_id) | Q(stock_points=scope.store_id) | Q(pk=self.request.user.pk)
                         | Q(staff_kind__in=(User.FIELD, User.OUTSOURCED))).distinct()

    def _out(self, user, status_code=200):
        user = User.objects.select_related("role", "stock_point").get(pk=user.pk)
        return Response(UserSerializer(user, context=self.get_serializer_context()).data, status=status_code)

    def create(self, request, *args, **kwargs):
        actor = request.user
        scope = StoreScope(actor)
        scope.require_assigned()
        writer = StaffWriteSerializer(data=request.data)
        writer.is_valid(raise_exception=True)
        data = writer.validated_data
        check_role_grant(actor, data.get("role"))
        for role in data.get("roles", []):
            check_role_grant(actor, role)
        kind = data.get("staff_kind", User.STORE)
        check_outsource(actor, kind)
        if kind != User.STORE:
            pass  # field / outsourced technicians belong to no store (cleared by the serializer)
        elif not scope.owner and data.get("stock_points"):
            raise PermissionDenied("Only the Owner can give staff access to more stores.")
        elif not scope.owner:
            # a store administrator adds staff to their own store only
            if "stock_point" in data and (data["stock_point"] is None or data["stock_point"].pk != scope.store_id):
                raise PermissionDenied("You can only add staff to your own store -- only the Owner sets other Store Locations.")
            # re-read: the status must be the current one, not the copy cached on the actor
            data["stock_point"] = StockPoint.objects.filter(pk=scope.store_id).first()
            require_active(data["stock_point"], "staff assignments")
        user = writer.save()
        log_admin_action(actor, "create", user, role=user.role_id, store=user.stock_point_id,
                         password="set" if user.has_usable_password() else "pending")
        return self._out(user, 201)

    def partial_update(self, request, *args, **kwargs):
        actor = request.user
        user = self.get_object()
        check_can_manage(actor, user, "edit")
        writer = StaffWriteSerializer(user, data=request.data, partial=True)
        writer.is_valid(raise_exception=True)
        data = writer.validated_data
        if "role" in data and data["role"] != user.role:
            check_role_grant(actor, data["role"])
        if "roles" in data:
            held = user.assigned_role_ids()
            for role in data["roles"]:
                if role.pk not in held:
                    check_role_grant(actor, role)
        new_kind = data.get("staff_kind", user.staff_kind)
        check_outsource(actor, user.staff_kind, new_kind)
        if new_kind != User.STORE:
            pass  # store-free: stock_point and stock_points are cleared by the serializer
        elif user.staff_kind != User.STORE and not StoreScope(actor).owner:
            # back to store staff: a store Admin brings them into the store they're working in
            data["stock_point"] = StockPoint.objects.filter(pk=StoreScope(actor).store_id).first()
            require_active(data["stock_point"], "staff assignments")
        elif "stock_point" in data and data["stock_point"] != user.stock_point:
            StoreScope(actor).require_owner("Only the Owner can change a staff member's Store Location.")
        if new_kind == User.STORE and "stock_points" in data and {s.pk for s in data["stock_points"]} != user.assigned_store_ids():
            StoreScope(actor).require_owner("Only the Owner can change which stores a staff member works at.")
        if data.get("is_active") is False and is_last_owner(user):
            raise ValidationError({"is_active": "This is the last active Owner account -- it can't be deactivated."})
        writer.save()
        if data.get("is_active") is False:
            revoke_sessions(user)
        log_admin_action(actor, "update", user, fields=",".join(sorted(data)))
        return self._out(user)

    def destroy(self, request, *args, **kwargs):
        actor = request.user
        StoreScope(actor).require_owner("Only the Owner can delete staff accounts. Deactivate the account instead.")
        user = self.get_object()
        check_can_manage(actor, user, "delete")
        if is_last_owner(user):
            raise ValidationError({"detail": "This is the last active Owner account -- it can't be deleted."})
        with transaction.atomic():
            linked = sorted({
                str(rel.related_model._meta.verbose_name_plural)
                for rel in user._meta.related_objects
                if rel.related_model not in deletable_with_user()
                and rel.related_model._base_manager.filter(**{rel.field.name: user}).exists()
            })
            if linked:
                return Response({
                    "code": "has_history",
                    "detail": "This account is referenced by business or audit records, so deleting it would break "
                              "that history. Deactivate it instead -- it can no longer sign in.",
                    "related_records": linked,
                }, status=status.HTTP_409_CONFLICT)
            target_id = user.pk
            try:
                user.delete()
            except ProtectedError:
                return Response({"code": "has_history", "detail": "This account has linked records. Deactivate it instead."},
                                status=status.HTTP_409_CONFLICT)
        user.pk = target_id
        log_admin_action(actor, "delete", user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="activity")
    def activity(self, request, pk=None):
        """
        Staff Activity Logs: one account's work timeline (Store Locator ->
        Staff list -> Logs, or My activity). Rules live in accounts.activity:
          - Ordinary Staff: only their OWN id -- any other id is a 403 before
            anything is looked up; entries limited to their Store Location.
          - Admin / Superuser: the store-scoped user lookup, then the target
            rule; an account the viewer may not read is a 404 exactly like
            an unknown id (no way to tell a hidden Superuser from a gap).
          - Only then the eligible entries (visible_logs) -- every count,
            filter, search and page below comes from that queryset.
        Oldest first. Each entry carries `seq`, its position in the viewer's
        complete eligible timeline (#1 = earliest), so numbers stay the same
        across pages and filters.
        Query: period (today|yesterday|week|month) or date_from / date_to
        (YYYY-MM-DD, in the configured TIME_ZONE), module, kind (created|
        updated|deleted|other), store (<id>|none), q.
        """
        from datetime import timedelta

        from django.conf import settings
        from django.db.migrations.recorder import MigrationRecorder
        from django.db.models import Count
        from django.http import Http404
        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from .activity import (
            MODULE_LABELS, STAFF, can_view_logs_of, can_view_own_logs, role_tier, viewer_modules, visible_logs,
        )
        from .serializers import ActivityLogSerializer

        viewer = request.user
        if not can_view_own_logs(viewer):
            raise PermissionDenied("You don't have access to activity logs.")
        if role_tier(viewer) == STAFF:
            # ordinary staff: their own timeline and nothing else -- no lookup, no hint
            if str(pk) != str(viewer.pk):
                raise PermissionDenied("You can only view your own activity.")
            target = User.objects.select_related("role", "stock_point").get(pk=viewer.pk)
        else:
            # one identical 404 for "no such account", "outside your store" and
            # "an account whose logs you may not read" -- nothing to tell them apart
            try:
                target = self.get_object()
            except Http404:
                target = None
            if target is None or not can_view_logs_of(viewer, target):
                raise NotFound("Not found.")
        eligible = visible_logs(viewer, target)

        # -- the period, resolved here in the configured TIME_ZONE ------------
        params = request.query_params
        today = timezone.localdate()
        period = params.get("period") or ""
        presets = {
            "today": (today, today),
            "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
            "week": (today - timedelta(days=today.weekday()), today),
            "month": (today.replace(day=1), today),
        }
        if period in presets:
            day_from, day_to = presets[period]
        else:
            period = ""
            day_from = day_to = None
            for key in ("date_from", "date_to"):
                if params.get(key):
                    day = parse_date(params[key])
                    if day is None:
                        raise ValidationError({key: "Use a date like 2026-10-29."})
                    if key == "date_from":
                        day_from = day
                    else:
                        day_to = day
            if day_from and day_to and day_from > day_to:
                raise ValidationError({"date_to": "The end date is before the start date."})

        qs = eligible.select_related("stock_point")
        filtered = bool(day_from or day_to)
        if day_from:
            qs = qs.filter(at__date__gte=day_from)
        if day_to:
            qs = qs.filter(at__date__lte=day_to)
        if params.get("q", "").strip():
            needle = params["q"].strip()[:100]
            qs = qs.filter(Q(description__icontains=needle) | Q(record_label__icontains=needle))
            filtered = True
        if params.get("module"):
            qs = qs.filter(module=params["module"])
            filtered = True
        kind = params.get("kind")
        if kind in ("created", "updated", "deleted"):
            qs = qs.filter(action=kind)
            filtered = True
        elif kind == "other":
            qs = qs.exclude(action__in=["created", "updated", "deleted"])
            filtered = True
        store = params.get("store")
        if store == "none":
            qs = qs.filter(stock_point__isnull=True)
            filtered = True
        elif store:
            try:
                qs = qs.filter(stock_point_id=int(store))
            except ValueError:
                raise ValidationError({"store": "Unknown store filter."})
            filtered = True

        qs = qs.order_by("at", "id")
        page = self.paginate_queryset(qs)
        # stable numbering over the WHOLE eligible timeline (oldest = #1)
        if not filtered:
            start = (self.paginator.page.number - 1) * self.paginator.page.paginator.per_page
            for i, entry in enumerate(page):
                entry.seq = start + i + 1
        else:
            for entry in page:
                entry.seq = eligible.filter(Q(at__lt=entry.at) | Q(at=entry.at, id__lte=entry.id)).count()
        response = self.get_paginated_response(ActivityLogSerializer(page, many=True).data)

        now = timezone.now()
        agg = eligible.aggregate(
            total=Count("id"),
            last_7_days=Count("id", filter=Q(at__gte=now - timedelta(days=7))),
            last_30_days=Count("id", filter=Q(at__gte=now - timedelta(days=30))),
            imported=Count("id", filter=Q(source="imported")),
        )
        first = eligible.order_by("at").values_list("at", flat=True).first()
        latest = eligible.order_by("-at").values_list("at", flat=True).first()
        by_module = eligible.order_by().values("module").annotate(n=Count("id")).order_by("-n")
        by_store = eligible.order_by().values("stock_point_id", "stock_point__name").annotate(n=Count("id")).order_by("-n")
        started = MigrationRecorder.Migration.objects.filter(app="accounts", name="0007_activitylog").values_list("applied", flat=True).first()
        sp = target.stock_point
        response.data.update({
            "staff": {
                "id": target.id, "username": target.username, "name": target.get_full_name() or target.username,
                "role": "Superuser" if target.is_superuser else (target.role.label if target.role_id else None),
                "is_active": target.is_active, "last_login": target.last_login, "sees_all_stores": sees_all_stores(target),
                "is_self": target.pk == viewer.pk,
                "store": {"id": sp.id, "name": sp.name, "kind": sp.kind, "address": sp.address, "phone": sp.phone} if sp else None,
            },
            "summary": {**agg, "first_at": first, "latest_at": latest, "tracking_since": started,
                        "by_module": [{"module": r["module"], "label": MODULE_LABELS.get(r["module"], r["module"]), "count": r["n"]} for r in by_module],
                        "by_store": [{"id": r["stock_point_id"], "name": r["stock_point__name"], "count": r["n"]} for r in by_store]},
            "range": {"period": period or None, "from": day_from, "to": day_to, "filtered": filtered},
            "timezone": settings.TIME_ZONE,
            "modules": [{"id": m, "label": MODULE_LABELS[m]} for m in viewer_modules(viewer) if m in MODULE_LABELS],
        })
        return response

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        data = UserSerializer(request.user, context=self.get_serializer_context()).data
        return Response({**data, **context_payload(request.user), "subscription": subscription_services.summary()})

    @action(detail=False, methods=["post"], url_path="me/change-password", throttle_classes=[PasswordChangeThrottle])
    def change_password(self, request):
        """
        Self-service password change. Always the requesting account -- any
        user id in the body is ignored. Signs out every other session (their
        refresh tokens are blacklisted) and returns a fresh token pair so this
        one stays signed in.
        """
        payload = ChangePasswordSerializer(data=request.data, context={"request": request})
        payload.is_valid(raise_exception=True)
        user = request.user
        user.set_password(payload.validated_data["new_password"])
        user.save(update_fields=["password"])
        revoke_sessions(user)
        fresh = RefreshToken.for_user(user)
        log_admin_action(user, "change-own-password", user)
        return Response({"detail": "Your password has been changed. Other signed-in sessions were signed out.",
                         "access": str(fresh.access_token), "refresh": str(fresh)})

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """Body: {"is_active": false | true}. Deactivating also signs the account out."""
        actor = request.user
        user = self.get_object()
        value = request.data.get("is_active")
        if not isinstance(value, bool):
            return Response({"detail": "is_active must be true or false."}, status=400)
        check_can_manage(actor, user, "reactivate" if value else "deactivate")
        if not value and is_last_owner(user):
            return Response({"detail": "This is the last active Owner account -- it can't be deactivated."}, status=400)
        user.is_active = value
        user.save(update_fields=["is_active"])
        if not value:
            revoke_sessions(user)
        log_admin_action(actor, "activate" if value else "deactivate", user)
        return self._out(user)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        """
        Reset ONE staff member's password. Body: {"delivery": "email" | "link"}.
        Their current password stops working and every session is signed out;
        they choose a new one through a single-use link valid for
        SETUP_LINK_HOURS. "email" sends it to their email address and is
        refused when no real email provider is configured (the console backend
        isn't a delivery). "link" returns it once, to this administrator only,
        to hand over in person.
        """
        actor = request.user
        user = self.get_object()
        check_can_manage(actor, user, "reset the password of")
        if not user.is_active:
            return Response({"detail": "This account is deactivated -- reactivate it before resetting its password."}, status=400)
        delivery = request.data.get("delivery")
        if delivery not in ("email", "link"):
            return Response({"detail": 'delivery must be "email" or "link".'}, status=400)
        if delivery == "email":
            if not user.email:
                return Response({"code": "no_email", "detail": "This staff member has no email address on file. Create a one-time link instead."}, status=400)
            if not email_delivery_configured():
                return Response({"code": "email_not_configured",
                                 "detail": "Email delivery isn't configured on this server (no EMAIL_HOST), so no email can be sent. "
                                           "Create a one-time link and give it to the staff member directly."}, status=400)
        user.set_unusable_password()
        user.save(update_fields=["password"])
        revoke_sessions(user)
        link = setup_link(user)  # after the save: the token is bound to the new (unusable) hash
        log_admin_action(actor, "reset-password", user, delivery=delivery)
        if delivery == "email":
            name = user.get_full_name() or user.username
            sent = send_email(
                user.email, f"Set your {settings.BUSINESS_NAME} CRM password",
                f"Hello {name},\n\nAn administrator reset the password for your account ({user.username}). "
                f"Choose a new password here within {SETUP_LINK_HOURS} hours:\n\n{link}\n\n"
                "The link works once. If you didn't expect this, contact your administrator.",
            )
            if sent.get("status") != "sent":
                return Response({"code": "email_failed",
                                 "detail": "The password was reset, but the email couldn't be delivered. "
                                           "Create a one-time link instead."}, status=502)
            return Response({"delivery": "email", "status": "sent", "email": user.email, "expires_in_hours": SETUP_LINK_HOURS})
        return Response({"delivery": "link", "setup_url": link, "expires_in_hours": SETUP_LINK_HOURS})

    @action(detail=True, methods=["post"], url_path="set-store")
    def set_store(self, request, pk=None):
        """
        Owner only: set (or clear, with null) a staff member's Store
        Location. Body: {"stock_point": <id of a physical shop> | null}.
        Online channels aren't places staff work from, so they're refused.
        """
        StoreScope(request.user).require_owner("Only the Owner can change a staff member's Store Location.")
        user = self.get_object()
        if sees_all_stores(user):
            return Response(
                {"detail": "This account is the Owner / Super Admin -- it already sees every store."},
                status=400,
            )
        if "stock_point" not in request.data:
            return Response({"detail": "stock_point is required (send null to unassign)."}, status=400)
        value = request.data.get("stock_point")
        stock_point = None
        if value not in (None, ""):
            try:
                stock_point = StockPoint.objects.filter(pk=int(value)).first()
            except (TypeError, ValueError):
                stock_point = None
            if stock_point is None:
                return Response({"detail": "No such store."}, status=400)
            if stock_point.kind != StockPoint.SHOP:
                return Response({"detail": f"{stock_point.name} is an online channel -- staff can only be assigned to a physical shop."}, status=400)
            require_active(stock_point, "staff assignments", current=user.stock_point_id)
        user.stock_point = stock_point
        user.save(update_fields=["stock_point"])
        log_admin_action(request.user, "set-store", user, store=user.stock_point_id)
        return self._out(user)

    @action(detail=True, methods=["post"], url_path="set-role")
    def set_role(self, request, pk=None):
        user = self.get_object()
        if user.is_superuser:
            return Response(
                {"detail": "This account is a superuser -- its access isn't controlled by role assignment."},
                status=400,
            )
        role_slug = request.data.get("role")
        if not role_slug:
            return Response({"detail": "role is required"}, status=400)
        if role_slug == "owner":
            return Response(
                {"detail": "The Owner role can't be assigned here -- it's tied to the superuser account itself."},
                status=400,
            )
        role = Role.objects.filter(slug=role_slug).first()
        if not role:
            return Response({"detail": f"No such role: {role_slug}"}, status=400)
        check_can_manage(request.user, user, "change the role of")
        check_role_grant(request.user, role)
        user.role = role
        user.save(update_fields=["role"])
        log_admin_action(request.user, "set-role", user, role=role.pk)
        return self._out(user)


class PasswordSetupView(APIView):
    """
    Public: the page a password-setup link opens (/set-password/<uid>/<token>).
    GET says whether the link is still usable; POST {new_password,
    confirm_password} sets the password. The account comes only from the
    verified link; the link stops working once a password is set.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    def _user(self, uidb64, token):
        try:
            pk = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None
        return user if setup_tokens.check_token(user, token) else None

    def get(self, request, uidb64, token):
        user = self._user(uidb64, token)
        if not user:
            return Response({"valid": False, "detail": "This link is invalid, has already been used, or has expired. Ask your administrator for a new one."}, status=400)
        return Response({"valid": True, "username": user.username, "first_name": user.first_name})

    def post(self, request, uidb64, token):
        user = self._user(uidb64, token)
        if not user:
            return Response({"valid": False, "detail": "This link is invalid, has already been used, or has expired. Ask your administrator for a new one."}, status=400)
        payload = SetPasswordSerializer(data=request.data, context={"user": user})
        payload.is_valid(raise_exception=True)
        user.set_password(payload.validated_data["new_password"])
        user.save(update_fields=["password"])
        revoke_sessions(user)
        log_admin_action(None, "set-password-via-link", user)
        return Response({"detail": "Your password has been set. You can now sign in."})

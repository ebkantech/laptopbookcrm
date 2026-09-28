from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import AuthenticationFailed, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import NotificationRule, Permission, Role, StaffNotification, User
from .permissions import HasPerm, IsStaffAccount
from .serializers import (
    NotificationRuleSerializer, PermissionSerializer, RoleSerializer, RoleWriteSerializer, StaffNotificationSerializer,
    UserSerializer,
)
from .throttling import LoginRateThrottle


class StaffTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Issue staff JWTs only; customer identities use cookie sessions."""

    def validate(self, attrs):
        data = super().validate(attrs)
        if hasattr(self.user, "customer_profile"):
            raise AuthenticationFailed("Invalid username or password")
        return data


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
        "list": None, "retrieve": None,
        "create": "roles.manage", "update": "roles.manage",
        "partial_update": "roles.manage", "destroy": "roles.manage",
    }

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return RoleWriteSerializer
        return RoleSerializer

    def create(self, request, *args, **kwargs):
        writer = self.get_serializer(data=request.data)
        writer.is_valid(raise_exception=True)
        role = writer.save()
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        writer = self.get_serializer(instance, data=request.data, partial=partial)
        writer.is_valid(raise_exception=True)
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


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Staff directory -- powers the "sign in as" switcher in the demo
    UI. Stays read-only for list/retrieve; the one write path is
    set_role below, deliberately narrow (it can only ever change the
    `role` field) so that granting roles.manage doesn't hand out
    anything close to full user-management access.
    """
    queryset = User.objects.select_related("role").all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, HasPerm]
    required_perms = {
        "list": None, "retrieve": None, "me": None,
        "set_role": "roles.manage",
    }

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        return Response(UserSerializer(request.user).data)

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
        user.role = role
        user.save(update_fields=["role"])
        return Response(UserSerializer(user).data)

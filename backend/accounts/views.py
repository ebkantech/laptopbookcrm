from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import AuthenticationFailed, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Permission, Role, User
from .permissions import IsStaffAccount
from .serializers import PermissionSerializer, RoleSerializer, UserSerializer
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


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only for everyone authenticated -- this is the permission
    matrix the "Roles & access" screen renders. Editing roles happens
    through the Django admin, gated separately.
    """
    queryset = Role.objects.prefetch_related("permissions").all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, IsStaffAccount]


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Staff directory -- powers the "sign in as" switcher in the demo
    UI. In a real deployment this stays read-only and identity comes
    from the JWT instead of a picker.
    """
    queryset = User.objects.select_related("role").all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsStaffAccount]

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        return Response(UserSerializer(request.user).data)

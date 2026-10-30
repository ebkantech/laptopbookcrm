from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    NotificationRuleViewSet, PasswordSetupView, PermissionViewSet, RoleViewSet, StaffNotificationViewSet, UserViewSet,
    csrf_cookie,
)

router = DefaultRouter()
router.register("permissions", PermissionViewSet, basename="permission")
router.register("roles", RoleViewSet, basename="role")
router.register("notification-rules", NotificationRuleViewSet, basename="notification-rule")
router.register("my-notifications", StaffNotificationViewSet, basename="staff-notification")
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("auth/csrf/", csrf_cookie, name="csrf-cookie"),
    path("auth/password-setup/<str:uidb64>/<str:token>/", PasswordSetupView.as_view(), name="password-setup"),
    *router.urls,
]

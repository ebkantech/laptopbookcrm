from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import NotificationRuleViewSet, PermissionViewSet, RoleViewSet, StaffNotificationViewSet, UserViewSet, csrf_cookie

router = DefaultRouter()
router.register("permissions", PermissionViewSet, basename="permission")
router.register("roles", RoleViewSet, basename="role")
router.register("notification-rules", NotificationRuleViewSet, basename="notification-rule")
router.register("my-notifications", StaffNotificationViewSet, basename="staff-notification")
router.register("users", UserViewSet, basename="user")

urlpatterns = [path("auth/csrf/", csrf_cookie, name="csrf-cookie"), *router.urls]

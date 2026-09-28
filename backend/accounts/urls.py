from rest_framework.routers import DefaultRouter

from .views import NotificationRuleViewSet, PermissionViewSet, RoleViewSet, StaffNotificationViewSet, UserViewSet

router = DefaultRouter()
router.register("permissions", PermissionViewSet, basename="permission")
router.register("roles", RoleViewSet, basename="role")
router.register("notification-rules", NotificationRuleViewSet, basename="notification-rule")
router.register("my-notifications", StaffNotificationViewSet, basename="staff-notification")
router.register("users", UserViewSet, basename="user")

urlpatterns = router.urls

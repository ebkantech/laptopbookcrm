from rest_framework.routers import DefaultRouter

from .views import WarrantyViewSet

router = DefaultRouter()
router.register("warranties", WarrantyViewSet, basename="warranty")

urlpatterns = router.urls

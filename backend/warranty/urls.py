from rest_framework.routers import DefaultRouter

from .views import WarrantyClaimViewSet, WarrantyViewSet

router = DefaultRouter()
router.register("warranties", WarrantyViewSet, basename="warranty")
router.register("warranty-claims", WarrantyClaimViewSet, basename="warranty-claim")

urlpatterns = router.urls

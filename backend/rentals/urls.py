from rest_framework.routers import DefaultRouter

from .views import RentalIssueViewSet, RentalViewSet

router = DefaultRouter()
router.register("rentals", RentalViewSet, basename="rental")
router.register("rental-issues", RentalIssueViewSet, basename="rentalissue")

urlpatterns = router.urls

from rest_framework.routers import DefaultRouter

from django.urls import path

from .views import RentalApprovalPublicView, RentalAssetViewSet, RentalIssueViewSet, RentalViewSet

router = DefaultRouter()
router.register("rentals", RentalViewSet, basename="rental")
router.register("rental-assets", RentalAssetViewSet, basename="rentalasset")
router.register("rental-issues", RentalIssueViewSet, basename="rentalissue")

urlpatterns = [
    path("public/rental-approvals/<str:token>/", RentalApprovalPublicView.as_view(), name="public-rental-approval"),
]
urlpatterns += router.urls

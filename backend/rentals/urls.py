from django.urls import path
from rest_framework.routers import DefaultRouter

from .handover import RentalApprovalPhotoView, RentalLineHandoverView, RentalLinePhotoUploadView, RentalLinePhotoView
from .views import RentalApprovalPublicView, RentalAssetViewSet, RentalIssueViewSet, RentalViewSet

router = DefaultRouter()
router.register("rentals", RentalViewSet, basename="rental")
router.register("rental-assets", RentalAssetViewSet, basename="rentalasset")
router.register("rental-issues", RentalIssueViewSet, basename="rentalissue")

urlpatterns = [
    path("public/rental-approvals/<str:token>/", RentalApprovalPublicView.as_view(), name="public-rental-approval"),
    path("public/rental-approvals/<str:token>/photos/<int:photo_id>/", RentalApprovalPhotoView.as_view(), name="public-rental-approval-photo"),
    path("rental-lines/<int:pk>/handover/", RentalLineHandoverView.as_view(), name="rental-line-handover"),
    path("rental-lines/<int:pk>/photos/", RentalLinePhotoUploadView.as_view(), name="rental-line-photo-upload"),
    path("rental-photos/<int:pk>/", RentalLinePhotoView.as_view(), name="rental-line-photo"),
]
urlpatterns += router.urls

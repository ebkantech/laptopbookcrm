from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    PortalAccessLogListView, PortalFeedbackView, PortalInviteViewSet, PortalInviteStatusView, PortalInvoicesView,
    PortalLocationView, PortalMeView, PortalRentalsView, PortalRepairsView, PortalVerifyView, PortalWarrantiesView,
)

router = DefaultRouter()
router.register("portal-invites", PortalInviteViewSet, basename="portalinvite")

urlpatterns = router.urls + [
    path("portal/invite-status/<uuid:token>/", PortalInviteStatusView.as_view(), name="portal-invite-status"),
    path("portal/verify/", PortalVerifyView.as_view(), name="portal-verify"),
    path("portal/location/", PortalLocationView.as_view(), name="portal-location"),
    path("portal/me/", PortalMeView.as_view(), name="portal-me"),
    path("portal/invoices/", PortalInvoicesView.as_view(), name="portal-invoices"),
    path("portal/repairs/", PortalRepairsView.as_view(), name="portal-repairs"),
    path("portal/rentals/", PortalRentalsView.as_view(), name="portal-rentals"),
    path("portal/warranties/", PortalWarrantiesView.as_view(), name="portal-warranties"),
    path("portal/feedback/", PortalFeedbackView.as_view(), name="portal-feedback"),
    path("portal-access-logs/", PortalAccessLogListView.as_view(), name="portal-access-logs"),
]

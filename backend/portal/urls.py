from django.urls import path
from rest_framework.routers import DefaultRouter

from .approval_link import RentalApprovalPortalView, RepairApprovalPortalView, RepairOrderApprovalPortalView
from .meta_webhook import meta_whatsapp_webhook
from .views import (
    PortalAccessLogListView, PortalFeedbackView, PortalInviteViewSet, PortalInviteStatusView, PortalInvoiceDetailView,
    PortalInvoicePdfView, PortalInvoicesView, PortalIssuesView, PortalSignedAgreementView,
    PortalLocationView, PortalMeView, PortalMessagesView, PortalRentalsView, PortalRepairsView, PortalResendOtpView, PortalVerifyView, PortalWarrantiesView,
    WhatsAppDeliveryWebhookView,
)

router = DefaultRouter()
router.register("portal-invites", PortalInviteViewSet, basename="portalinvite")

urlpatterns = router.urls + [
    path("portal/invite-status/<uuid:token>/", PortalInviteStatusView.as_view(), name="portal-invite-status"),
    path("portal/verify/", PortalVerifyView.as_view(), name="portal-verify"),
    # "Open my portal" on the rental / repair approval pages
    path("public/rental-approvals/<str:token>/portal/", RentalApprovalPortalView.as_view(), name="public-rental-approval-portal"),
    path("public/repair-approvals/<str:token>/portal/", RepairApprovalPortalView.as_view(), name="public-repair-approval-portal"),
    path("public/repair-order-approvals/<str:token>/portal/", RepairOrderApprovalPortalView.as_view(), name="public-repair-order-approval-portal"),
    path("portal/resend-otp/", PortalResendOtpView.as_view(), name="portal-resend-otp"),
    path("portal/location/", PortalLocationView.as_view(), name="portal-location"),
    path("portal/me/", PortalMeView.as_view(), name="portal-me"),
    path("portal/invoices/", PortalInvoicesView.as_view(), name="portal-invoices"),
    path("portal/invoices/<int:invoice_id>/", PortalInvoiceDetailView.as_view(), name="portal-invoice-detail"),
    path("portal/invoices/<int:invoice_id>/pdf/", PortalInvoicePdfView.as_view(), name="portal-invoice-pdf"),
    path("portal/invoices/<int:invoice_id>/download/", PortalInvoicePdfView.as_view(), name="portal-invoice-download"),
    path("portal/repairs/", PortalRepairsView.as_view(), name="portal-repairs"),
    path("portal/rentals/", PortalRentalsView.as_view(), name="portal-rentals"),
    path("portal/rentals/<int:rental_id>/signed-agreement/", PortalSignedAgreementView.as_view(), name="portal-signed-agreement"),
    path("portal/issues/", PortalIssuesView.as_view(), name="portal-issues"),
    path("portal/warranties/", PortalWarrantiesView.as_view(), name="portal-warranties"),
    path("portal/feedback/", PortalFeedbackView.as_view(), name="portal-feedback"),
    path("portal/messages/", PortalMessagesView.as_view(), name="portal-messages"),
    path("portal-access-logs/", PortalAccessLogListView.as_view(), name="portal-access-logs"),
    path("portal/whatsapp-webhook/", WhatsAppDeliveryWebhookView.as_view(), name="portal-whatsapp-webhook"),
    path("whatsapp/meta-webhook/", meta_whatsapp_webhook, name="whatsapp-meta-webhook"),
]

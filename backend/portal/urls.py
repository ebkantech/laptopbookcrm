from django.urls import path
from rest_framework.routers import DefaultRouter

from .meta_webhook import meta_whatsapp_webhook
from .views import (
    PortalAccessLogListView, PortalFeedbackView, PortalInviteViewSet, PortalInviteStatusView, PortalInvoiceDetailView,
    PortalInvoicePdfView, PortalInvoicesView,
    PortalLocationView, PortalMeView, PortalRentalsView, PortalRepairsView, PortalResendOtpView, PortalVerifyView, PortalWarrantiesView,
    WhatsAppDeliveryWebhookView,
)

router = DefaultRouter()
router.register("portal-invites", PortalInviteViewSet, basename="portalinvite")

urlpatterns = router.urls + [
    path("portal/invite-status/<uuid:token>/", PortalInviteStatusView.as_view(), name="portal-invite-status"),
    path("portal/verify/", PortalVerifyView.as_view(), name="portal-verify"),
    path("portal/resend-otp/", PortalResendOtpView.as_view(), name="portal-resend-otp"),
    path("portal/location/", PortalLocationView.as_view(), name="portal-location"),
    path("portal/me/", PortalMeView.as_view(), name="portal-me"),
    path("portal/invoices/", PortalInvoicesView.as_view(), name="portal-invoices"),
    path("portal/invoices/<int:invoice_id>/", PortalInvoiceDetailView.as_view(), name="portal-invoice-detail"),
    path("portal/invoices/<int:invoice_id>/pdf/", PortalInvoicePdfView.as_view(), name="portal-invoice-pdf"),
    path("portal/invoices/<int:invoice_id>/download/", PortalInvoicePdfView.as_view(), name="portal-invoice-download"),
    path("portal/repairs/", PortalRepairsView.as_view(), name="portal-repairs"),
    path("portal/rentals/", PortalRentalsView.as_view(), name="portal-rentals"),
    path("portal/warranties/", PortalWarrantiesView.as_view(), name="portal-warranties"),
    path("portal/feedback/", PortalFeedbackView.as_view(), name="portal-feedback"),
    path("portal-access-logs/", PortalAccessLogListView.as_view(), name="portal-access-logs"),
    path("portal/whatsapp-webhook/", WhatsAppDeliveryWebhookView.as_view(), name="portal-whatsapp-webhook"),
    path("whatsapp/meta-webhook/", meta_whatsapp_webhook, name="whatsapp-meta-webhook"),
]

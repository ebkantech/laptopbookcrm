from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import InvoiceViewSet, RazorpayWebhookView

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = router.urls + [
    path("payments/razorpay-webhook/", RazorpayWebhookView.as_view(), name="razorpay-webhook"),
]

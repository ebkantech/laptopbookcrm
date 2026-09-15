from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import RepairApprovalPublicView, RepairInvoiceViewSet, RepairTicketViewSet

router = DefaultRouter()
router.register("tickets", RepairTicketViewSet, basename="repairticket")
router.register("repair-invoices", RepairInvoiceViewSet, basename="repairinvoice")

urlpatterns = [
    path(
        "public/repair-approvals/<str:token>/",
        RepairApprovalPublicView.as_view(),
        name="public-repair-approval",
    ),
]
urlpatterns += router.urls

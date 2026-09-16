from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    RepairApprovalPublicView,
    RepairInvoiceViewSet,
    RepairOrderApprovalPublicView,
    RepairOrderViewSet,
    RepairTicketViewSet,
)

router = DefaultRouter()
router.register("tickets", RepairTicketViewSet, basename="repairticket")
router.register("repair-orders", RepairOrderViewSet, basename="repairorder")
router.register("repair-invoices", RepairInvoiceViewSet, basename="repairinvoice")

urlpatterns = [
    path(
        "public/repair-approvals/<str:token>/",
        RepairApprovalPublicView.as_view(),
        name="public-repair-approval",
    ),
    path(
        "public/repair-order-approvals/<str:token>/",
        RepairOrderApprovalPublicView.as_view(),
        name="public-repair-order-approval",
    ),
]
urlpatterns += router.urls

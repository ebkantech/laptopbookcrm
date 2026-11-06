from django.urls import path
from rest_framework.routers import DefaultRouter

from .reports import RepairStaffReportView
from .views import (
    RepairApprovalPublicView,
    RepairOrderApprovalPublicView,
    RepairOrderViewSet,
    RepairPartSearchView,
    RepairPartSerialCheckView,
    RepairTicketViewSet,
)

router = DefaultRouter()
router.register("tickets", RepairTicketViewSet, basename="repairticket")
router.register("repair-orders", RepairOrderViewSet, basename="repairorder")

urlpatterns = [
    path("repair-parts/", RepairPartSearchView.as_view(), name="repair-parts"),
    path("repair-parts/check-serial/", RepairPartSerialCheckView.as_view(), name="repair-parts-check-serial"),
    path("repair-staff-report/", RepairStaffReportView.as_view(), name="repair-staff-report"),
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

from rest_framework.routers import DefaultRouter

from .views import RepairInvoiceViewSet, RepairTicketViewSet

router = DefaultRouter()
router.register("tickets", RepairTicketViewSet, basename="repairticket")
router.register("repair-invoices", RepairInvoiceViewSet, basename="repairinvoice")

urlpatterns = router.urls

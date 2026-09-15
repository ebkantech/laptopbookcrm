from rest_framework.routers import DefaultRouter

from .views import BankAccountViewSet, BankEntryViewSet, CashEntryViewSet

router = DefaultRouter()
router.register("cash-entries", CashEntryViewSet, basename="cashentry")
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("bank-entries", BankEntryViewSet, basename="bankentry")

urlpatterns = router.urls

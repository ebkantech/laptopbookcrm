from django.urls import path
from rest_framework.routers import DefaultRouter

from .expense_views import ExpenseAttachmentFileView, ExpenseCategoryViewSet, ExpenseViewSet
from .staff_advances import StaffAdvanceDetailView, StaffAdvanceListView
from .views import BankAccountViewSet, BankEntryViewSet, CashEntryViewSet

router = DefaultRouter()
router.register("cash-entries", CashEntryViewSet, basename="cashentry")
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("bank-entries", BankEntryViewSet, basename="bankentry")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("expense-categories", ExpenseCategoryViewSet, basename="expensecategory")

urlpatterns = router.urls + [
    path("expense-attachments/<int:pk>/file/", ExpenseAttachmentFileView.as_view(), name="expense-attachment-file"),
    path("staff-advances/", StaffAdvanceListView.as_view(), name="staff-advances"),
    path("staff-advances/<int:pk>/", StaffAdvanceDetailView.as_view(), name="staff-advance-detail"),
]

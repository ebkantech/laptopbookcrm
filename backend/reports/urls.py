from django.urls import path

from .views import (
    FeedbackEngagementReportView, FinancialSummaryReportView, InventoryStockReportView, PartyReportView,
    ProfitLossStoresView, ProfitLossTransactionsView, ProfitLossView, RentalPortfolioReportView, RepairTurnaroundReportView, SalesSummaryReportView,
)

urlpatterns = [
    path("reports/financial-summary/", FinancialSummaryReportView.as_view(), name="report-financial-summary"),
    path("reports/sales-summary/", SalesSummaryReportView.as_view(), name="report-sales-summary"),
    path("reports/rental-portfolio/", RentalPortfolioReportView.as_view(), name="report-rental-portfolio"),
    path("reports/repair-turnaround/", RepairTurnaroundReportView.as_view(), name="report-repair-turnaround"),
    path("reports/party-report/", PartyReportView.as_view(), name="report-party"),
    path("reports/feedback-engagement/", FeedbackEngagementReportView.as_view(), name="report-feedback-engagement"),
    path("reports/profit-loss/", ProfitLossView.as_view(), name="report-profit-loss"),
    path("reports/profit-loss/transactions/", ProfitLossTransactionsView.as_view(), name="report-profit-loss-transactions"),
    path("reports/profit-loss/stores/", ProfitLossStoresView.as_view(), name="report-profit-loss-stores"),
    path("reports/inventory-stock/", InventoryStockReportView.as_view(), name="report-inventory-stock"),
]

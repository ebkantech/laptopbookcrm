from django.urls import path

from .views import (
    FeedbackEngagementReportView, FinancialSummaryReportView, InventoryStockReportView, PartyReportView,
    RentalPortfolioReportView, RepairTurnaroundReportView, SalesSummaryReportView,
)

urlpatterns = [
    path("reports/financial-summary/", FinancialSummaryReportView.as_view(), name="report-financial-summary"),
    path("reports/sales-summary/", SalesSummaryReportView.as_view(), name="report-sales-summary"),
    path("reports/rental-portfolio/", RentalPortfolioReportView.as_view(), name="report-rental-portfolio"),
    path("reports/repair-turnaround/", RepairTurnaroundReportView.as_view(), name="report-repair-turnaround"),
    path("reports/party-report/", PartyReportView.as_view(), name="report-party"),
    path("reports/feedback-engagement/", FeedbackEngagementReportView.as_view(), name="report-feedback-engagement"),
    path("reports/inventory-stock/", InventoryStockReportView.as_view(), name="report-inventory-stock"),
]

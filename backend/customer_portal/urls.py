from django.urls import path

from .views import (
    CustomerActivateView,
    CustomerCsrfView,
    CustomerDashboardView,
    CustomerLoginView,
    CustomerLogoutView,
    CustomerMeView,
    CustomerRepairApprovalDecisionView,
    CustomerRepairOrderApprovalDecisionView,
    CustomerResetPasswordView,
    CustomerRentalApprovalDecisionView,
)


urlpatterns = [
    path("auth/csrf/", CustomerCsrfView.as_view(), name="customer-csrf"),
    path("auth/login/", CustomerLoginView.as_view(), name="customer-login"),
    path("auth/logout/", CustomerLogoutView.as_view(), name="customer-logout"),
    path("auth/activate/<str:token>/", CustomerActivateView.as_view(), name="customer-activate"),
    path("auth/reset-password/<str:token>/", CustomerResetPasswordView.as_view(), name="customer-reset-password"),
    path("me/", CustomerMeView.as_view(), name="customer-me"),
    path("dashboard/", CustomerDashboardView.as_view(), name="customer-dashboard"),
    path("rental-approvals/<int:pk>/decision/", CustomerRentalApprovalDecisionView.as_view(), name="customer-rental-decision"),
    path("repair-approvals/<int:pk>/decision/", CustomerRepairApprovalDecisionView.as_view(), name="customer-repair-decision"),
    path("repair-order-approvals/<int:pk>/decision/", CustomerRepairOrderApprovalDecisionView.as_view(), name="customer-repair-order-decision"),
]

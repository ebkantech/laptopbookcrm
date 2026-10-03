from django.urls import path

from .views import DashboardLayoutView, DashboardView

urlpatterns = [
    path("summary/", DashboardView.as_view(), name="dashboard-summary"),
    path("layout/", DashboardLayoutView.as_view(), name="dashboard-layout"),
]

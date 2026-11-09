from django.urls import path

from .details import MetricDetailView
from .views import DashboardLayoutView, DashboardView

urlpatterns = [
    path("summary/", DashboardView.as_view(), name="dashboard-summary"),
    path("layout/", DashboardLayoutView.as_view(), name="dashboard-layout"),
    path("detail/<str:metric>/", MetricDetailView.as_view(), name="dashboard-detail"),
]

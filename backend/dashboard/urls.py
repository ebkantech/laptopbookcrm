from django.urls import path

from .views import DashboardView

urlpatterns = [path("summary/", DashboardView.as_view(), name="dashboard-summary")]

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import LeadApprovalPublicView, LeadViewSet

router = DefaultRouter()
router.register("leads", LeadViewSet, basename="lead")

urlpatterns = [
    path("public/lead-approvals/<str:token>/", LeadApprovalPublicView.as_view(), name="public-lead-approval"),
]
urlpatterns += router.urls

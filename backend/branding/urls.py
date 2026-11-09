from django.urls import path

from .views import BrandingView, BusinessView, MessageView, PreviewView

urlpatterns = [
    path("branding/", BrandingView.as_view(), name="branding"),
    path("branding/business/", BusinessView.as_view(), name="branding-business"),
    path("branding/messages/<str:key>/", MessageView.as_view(), name="branding-message"),
    path("branding/messages/<str:key>/preview/", PreviewView.as_view(), name="branding-preview"),
]

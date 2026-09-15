from rest_framework.routers import DefaultRouter

from .views import CampaignViewSet, WhatsAppOrderViewSet

router = DefaultRouter()
router.register("campaigns", CampaignViewSet, basename="campaign")
router.register("whatsapp-orders", WhatsAppOrderViewSet, basename="whatsapporder")

urlpatterns = router.urls

from rest_framework.routers import DefaultRouter

from .views import MessageRecordViewSet, PartyViewSet

router = DefaultRouter()
router.register("parties", PartyViewSet, basename="party")
router.register(r"parties/(?P<party_pk>\d+)/messages", MessageRecordViewSet, basename="party-message")

urlpatterns = router.urls

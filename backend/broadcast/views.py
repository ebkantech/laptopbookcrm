import random

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm, IsStaffAccount
from .models import Campaign, WhatsAppOrder
from .serializers import CampaignSerializer, WhatsAppOrderSerializer


class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "broadcast.send"

    def perform_create(self, serializer):
        # simulated delivery numbers -- swap for a real WhatsApp/email
        # provider webhook callback in production
        sent = random.randint(80, 430)
        serializer.save(sent=sent, opened=round(sent * 0.68))


class WhatsAppOrderViewSet(viewsets.ModelViewSet):
    queryset = WhatsAppOrder.objects.select_related("party").all()
    serializer_class = WhatsAppOrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]

    @action(detail=True, methods=["post"])
    def quote(self, request, pk=None):
        order = self.get_object()
        order.status = WhatsAppOrder.QUOTED
        order.save(update_fields=["status"])
        return Response(WhatsAppOrderSerializer(order).data)

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Message, Party
from .serializers import MessageSerializer, PartyDetailSerializer, PartySerializer


class PartyViewSet(viewsets.ModelViewSet):
    queryset = Party.objects.prefetch_related("invoices__items", "invoices__stock_point", "messages").all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return PartyDetailSerializer if self.action == "retrieve" else PartySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    @action(detail=True, methods=["post"], url_path="message")
    def send_message(self, request, pk=None):
        party = self.get_object()
        msg = Message.objects.create(
            party=party, channel=request.data.get("channel", "whatsapp"),
            direction="out", body=request.data["body"],
        )
        return Response(MessageSerializer(msg).data, status=201)

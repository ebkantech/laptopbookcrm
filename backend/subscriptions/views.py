from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffAccount

from . import services


class SubscriptionView(APIView):
    """The current plan and the price list. Plans are activated from the server."""
    permission_classes = [IsStaffAccount]

    def get(self, request):
        return Response({**services.summary(), "plans": services.plans()})

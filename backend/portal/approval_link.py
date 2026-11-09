"""
"Open my portal" from a rental or repair approval page:
POST /api/public/<rental|repair|repair-order>-approvals/<token>/portal/

The approval token (a 24-hour link sent to the customer's phone) only hands
back the portal LINK; signing in still takes the one-time code emailed to the
customer (portal.services.portal_link_from_approval).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .services import portal_link_from_approval


class ApprovalPortalView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = ""  # set by each approval type

    def party_for(self, token):
        raise NotImplementedError

    def post(self, request, token):
        party = self.party_for(token)
        try:
            data = portal_link_from_approval(party)
        except DjangoValidationError as error:
            response = Response({"detail": " ".join(error.messages)}, status=400)
        else:
            response = Response(data)
        response["Cache-Control"] = "no-store, private"
        response["Referrer-Policy"] = "no-referrer"
        return response


class RentalApprovalPortalView(ApprovalPortalView):
    throttle_scope = "rental_approval"

    def party_for(self, token):
        from rentals.services import get_public_approval

        return get_public_approval(token).rental.party


class RepairApprovalPortalView(ApprovalPortalView):
    throttle_scope = "repair_approval"

    def party_for(self, token):
        from repairs.services import get_public_approval

        return get_public_approval(token).estimate.ticket.party


class RepairOrderApprovalPortalView(ApprovalPortalView):
    throttle_scope = "repair_approval"

    def party_for(self, token):
        from repairs.services import get_public_order_approval

        return get_public_order_approval(token).order.party

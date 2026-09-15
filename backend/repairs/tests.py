from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Service, StockPoint
from parties.models import Party
from repairs.models import RepairApproval, RepairTicket
from repairs.services import customer_decide, finalize_estimate, issue_approval_link


class RepairApprovalWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="approval-admin", password="safe-test-password", is_superuser=True
        )
        self.party = Party.objects.create(
            name="Approval Customer", type=Party.RETAIL, phone="9876543210", joined=date.today()
        )
        self.stock_point = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.service = Service.objects.create(
            slug="test-diagnosis", label="Diagnostic repair", segment=Service.SOFTWARE, charge=1200
        )
        self.ticket = RepairTicket.objects.create(
            code="RPR-TEST-1", party=self.party, brand="Test", model_name="Laptop",
            stock_point=self.stock_point, issue="Will not start", status=RepairTicket.DIAGNOSING,
            received=date.today(),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_customer_approval_is_required_before_work_and_records_decision(self):
        blocked = self.client.post(f"/api/tickets/{self.ticket.id}/advance/", format="json")
        self.assertEqual(blocked.status_code, 400)

        estimate = finalize_estimate(
            self.ticket, self.user,
            [{"service": self.service, "description": "Diagnostic repair", "quantity": 1, "unit_price": 1200}],
        )
        approval, approval_url, _ = issue_approval_link(self.ticket, self.user)
        raw_token = approval_url.rsplit("/", 1)[-1]

        self.assertEqual(approval.status, RepairApproval.PENDING)
        self.assertNotEqual(approval.token_hash, raw_token)
        self.assertIsNotNone(approval.expires_at)

        customer_decide(raw_token, "approve", consent=True)
        estimate.refresh_from_db()
        self.assertTrue(estimate.is_approved)

        advanced = self.client.post(f"/api/tickets/{self.ticket.id}/advance/", format="json")
        self.assertEqual(advanced.status_code, 200)
        self.assertEqual(advanced.data["status"], RepairTicket.IN_PROGRESS)

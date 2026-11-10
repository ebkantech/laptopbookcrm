"""POST /api/tickets/<id>/approval-link/ ("Generate 24 hour link") runs
issue_approval_link() with no surrounding transaction. These tests use
TransactionTestCase (real autocommit, like runserver) because TestCase wraps
every test in a transaction, which hid the select_for_update() error."""
import threading
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Service, StockPoint
from parties.models import Party
from repairs.models import RepairApproval, RepairTicket
from repairs.services import APPROVAL_LINK_TTL, approval_token_hash, finalize_estimate, issue_approval_link

PORTAL = "https://portal.example.test"


@override_settings(PUBLIC_FRONTEND_URL=PORTAL)
class GenerateApprovalLinkTransactionTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tx-admin", password="x-safe-pass", is_superuser=True)
        party = Party.objects.create(name="Tx Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        store = StockPoint.objects.create(slug="tx-shop", name="Tx Shop", kind=StockPoint.SHOP)
        service = Service.objects.create(slug="tx-diag", label="Diagnosis", segment=Service.SOFTWARE, charge=500)
        self.ticket = RepairTicket.objects.create(
            code="RPR-TX-1", party=party, brand="Dell", model_name="L5", stock_point=store,
            issue="No power", status=RepairTicket.DIAGNOSING, received=date.today(),
        )
        finalize_estimate(self.ticket, self.user, [{"service": service, "description": "Diagnosis",
                                                    "quantity": 1, "unit_price": 500}])
        self.endpoint = f"/api/tickets/{self.ticket.pk}/approval-link/"

    def client_for(self):
        client = APIClient()
        client.force_authenticate(self.user)
        return client

    def approvals(self):
        return RepairApproval.objects.filter(estimate__ticket=self.ticket)

    def test_service_call_outside_a_transaction_succeeds(self):
        self.assertFalse(connection.in_atomic_block)
        approval, url, wa_url = issue_approval_link(self.ticket, self.user)
        self.assertTrue(url.startswith(f"{PORTAL}/repair-approval/"), url)
        self.assertEqual(approval.status, RepairApproval.PENDING)
        self.assertTrue(wa_url.startswith("https://wa.me/"))

    def test_generate_link_endpoint_succeeds_with_24_hour_expiry(self):
        before = timezone.now()
        r = self.client_for().post(self.endpoint, {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        for key in ("ticket", "approval_url", "whatsapp_url", "expires_at", "whatsapp_provider", "send_path"):
            self.assertIn(key, body)
        self.assertTrue(body["approval_url"].startswith(f"{PORTAL}/repair-approval/"), body["approval_url"])
        self.assertIn("portal.example.test", body["whatsapp_url"])
        approval = self.approvals().get(status=RepairApproval.PENDING)
        self.assertEqual(approval.token_hash, approval_token_hash(body["approval_url"].rsplit("/", 1)[-1]))
        self.assertEqual(APPROVAL_LINK_TTL.total_seconds(), 24 * 3600)
        self.assertAlmostEqual((approval.expires_at - before).total_seconds(), 24 * 3600, delta=60)
        # the generated link opens the public approval API
        token = body["approval_url"].rsplit("/", 1)[-1]
        self.assertEqual(APIClient().get(f"/api/public/repair-approvals/{token}/").status_code, 200)

    def test_regenerating_revokes_the_previous_link(self):
        client = self.client_for()
        first = client.post(self.endpoint, {}, format="json").json()["approval_url"]
        second = client.post(self.endpoint, {}, format="json").json()["approval_url"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.approvals().filter(status=RepairApproval.PENDING).count(), 1)
        self.assertEqual(self.approvals().get(status=RepairApproval.PENDING).token_hash,
                         approval_token_hash(second.rsplit("/", 1)[-1]))
        self.assertEqual(self.approvals().get(token_hash=approval_token_hash(first.rsplit("/", 1)[-1])).status,
                         RepairApproval.REVOKED)
        self.assertEqual(APIClient().get(f"/api/public/repair-approvals/{first.rsplit('/', 1)[-1]}/").status_code, 410)

    def test_concurrent_requests_leave_exactly_one_pending_link(self):
        if connection.vendor != "postgresql":
            self.skipTest("row locks need PostgreSQL")
        workers = 4
        barrier = threading.Barrier(workers)
        statuses, errors = [], []

        def generate():
            try:
                barrier.wait(timeout=10)
                statuses.append(self.client_for().post(self.endpoint, {}, format="json").status_code)
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=generate) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(statuses, [200] * workers)
        self.assertEqual(self.approvals().filter(status=RepairApproval.PENDING).count(), 1)
        self.assertEqual(self.approvals().filter(status=RepairApproval.REVOKED).count(), workers - 1)

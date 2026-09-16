from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Service, StockPoint
from parties.models import Party
from repairs.models import RepairApproval, RepairOrder, RepairOrderApproval, RepairTicket, RepairTicketEvent
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

    def test_bulk_order_combines_device_estimates_into_one_secure_approval(self):
        created = self.client.post(
            "/api/repair-orders/",
            {
                "party": self.party.pk,
                "stock_point": self.stock_point.pk,
                "received": date.today().isoformat(),
                "payment": RepairTicket.FULL,
                "devices": [
                    {
                        "brand": "Dell",
                        "model_name": "Latitude 5420",
                        "serial": "BULK-SERIAL-1",
                        "issue": "No power",
                        "service_ids": [self.service.pk],
                    },
                    {
                        "brand": "Lenovo",
                        "model_name": "ThinkPad T14",
                        "serial": "BULK-SERIAL-2",
                        "issue": "Broken screen",
                        "service_ids": [self.service.pk],
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["repair_type"], "bulk")
        self.assertEqual(len(created.data["tickets"]), 2)

        order = RepairOrder.objects.get(pk=created.data["id"])
        first_ticket = order.tickets.order_by("id").first()
        readiness_before = self.client.get(f"/api/tickets/{first_ticket.pk}/")
        self.assertEqual(readiness_before.status_code, 200)
        self.assertFalse(readiness_before.data["combined_approval_ready"])
        self.assertEqual(len(readiness_before.data["order_progress"]), 2)
        self.assertTrue(all(not item["estimate_finalized"] for item in readiness_before.data["order_progress"]))

        for ticket in order.tickets.all():
            ticket.status = RepairTicket.DIAGNOSING
            ticket.save(update_fields=["status"])
            finalize_estimate(
                ticket,
                self.user,
                [{
                    "service": self.service,
                    "description": f"Repair {ticket.code}",
                    "quantity": 1,
                    "unit_price": 1200,
                }],
            )

        readiness_after = self.client.get(f"/api/tickets/{first_ticket.pk}/")
        self.assertEqual(readiness_after.status_code, 200)
        self.assertTrue(readiness_after.data["combined_approval_ready"])
        self.assertTrue(all(item["estimate_finalized"] for item in readiness_after.data["order_progress"]))

        link_response = self.client.post(f"/api/repair-orders/{order.pk}/approval-link/")
        self.assertEqual(link_response.status_code, 200)
        raw_token = link_response.data["approval_url"].rsplit("/", 1)[-1]

        public_client = APIClient()
        public_get = public_client.get(f"/api/public/repair-order-approvals/{raw_token}/")
        self.assertEqual(public_get.status_code, 200)
        self.assertEqual(public_get.data["repair_type"], "bulk")
        self.assertEqual(len(public_get.data["devices"]), 2)
        self.assertEqual(public_get.data["grand_total"], 2400)
        self.assertNotIn("phone", public_get.data["customer"])
        self.assertEqual(public_get["Cache-Control"], "no-store, private")

        # Revising one child estimate invalidates the whole old combined link.
        revised_ticket = order.tickets.order_by("id").first()
        finalize_estimate(
            revised_ticket,
            self.user,
            [{
                "service": self.service,
                "description": f"Revised repair {revised_ticket.code}",
                "quantity": 1,
                "unit_price": 1300,
            }],
        )
        stale = public_client.post(
            f"/api/public/repair-order-approvals/{raw_token}/",
            {"decision": "approve", "consent": True},
            format="json",
        )
        self.assertEqual(stale.status_code, 410)

        replacement = self.client.post(f"/api/repair-orders/{order.pk}/approval-link/")
        self.assertEqual(replacement.status_code, 200)
        raw_token = replacement.data["approval_url"].rsplit("/", 1)[-1]
        replacement_get = public_client.get(f"/api/public/repair-order-approvals/{raw_token}/")
        self.assertEqual(replacement_get.data["grand_total"], 2500)

        decision = public_client.post(
            f"/api/public/repair-order-approvals/{raw_token}/",
            {"decision": "approve", "consent": True},
            format="json",
        )
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.data["status"], RepairOrderApproval.APPROVED)
        for ticket in order.tickets.all():
            self.assertTrue(ticket.current_estimate.is_approved)
            self.assertEqual(
                ticket.current_estimate.approved_record.order_approval.order_id,
                order.pk,
            )

    def test_bulk_order_requires_unique_serials(self):
        response = self.client.post(
            "/api/repair-orders/",
            {
                "party": self.party.pk,
                "stock_point": self.stock_point.pk,
                "received": date.today().isoformat(),
                "devices": [
                    {"brand": "Dell", "model_name": "A", "serial": "SAME", "issue": "A", "service_ids": [self.service.pk]},
                    {"brand": "HP", "model_name": "B", "serial": "same", "issue": "B", "service_ids": [self.service.pk]},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_approved_ticket_changes_require_reason_and_are_audited(self):
        estimate = finalize_estimate(
            self.ticket,
            self.user,
            [{"service": self.service, "description": "Diagnostic repair", "quantity": 1, "unit_price": 1200}],
        )
        _, approval_url, _ = issue_approval_link(self.ticket, self.user)
        customer_decide(approval_url.rsplit("/", 1)[-1], "approve", consent=True)
        self.assertTrue(estimate.approved_record is not None)

        blocked = self.client.patch(
            f"/api/tickets/{self.ticket.pk}/",
            {"issue": "Updated internal diagnosis"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)
        changed = self.client.patch(
            f"/api/tickets/{self.ticket.pk}/",
            {"issue": "Updated internal diagnosis", "internal_change_reason": "Technician confirmed additional symptom"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)
        event = self.ticket.events.get(event_type=RepairTicketEvent.MODIFIED_AFTER_APPROVAL)
        self.assertEqual(event.metadata["before"]["issue"], "Will not start")
        self.assertEqual(event.metadata["after"]["issue"], "Updated internal diagnosis")

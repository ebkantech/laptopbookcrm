from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role
from parties.models import Party
from rentals.models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalLine
from rentals.services import RentalApprovalLinkGone, customer_decide, issue_approval_link


class RentalApprovalWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rental-approval-admin", password="safe-test-password", is_superuser=True
        )
        self.party = Party.objects.create(
            name="Bulk Rental Customer", type=Party.RENTAL, phone="9876543210", joined=date.today(),
            customer_classification=Party.BUSINESS,
        )
        self.rental = Rental.objects.create(
            party=self.party,
            agreement_code="RNT-TEST-1",
            product_label="Two rental laptops",
            monthly_fee=4500,
            start=date.today(),
            tenure_months=6,
            last_payment=date.today(),
        )
        self.asset_one = RentalAsset.objects.create(
            asset_tag="AST-TEST-1", serial_number="SERIAL-TEST-1", brand="Dell", model_name="Latitude 5420"
        )
        self.asset_two = RentalAsset.objects.create(
            asset_tag="AST-TEST-2", serial_number="SERIAL-TEST-2", brand="Lenovo", model_name="ThinkPad T14"
        )
        RentalLine.objects.create(rental=self.rental, asset=self.asset_one, monthly_fee=2000)
        RentalLine.objects.create(rental=self.rental, asset=self.asset_two, monthly_fee=2500)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_bulk_snapshot_is_immutable_and_customer_approval_rents_all_assets(self):
        approval, approval_url = issue_approval_link(self.rental, self.user)
        raw_token = approval_url.rsplit("/", 1)[-1]

        self.assertEqual(approval.snapshot["rental_type"], "bulk")
        self.assertEqual(approval.snapshot["total_monthly_fee"], 4500)
        self.assertEqual(len(approval.snapshot["items"]), 2)
        self.assertNotEqual(approval.token_hash, raw_token)
        self.assertEqual(self.rental.approvals.count(), 1)

        public_client = APIClient()
        public_get = public_client.get(f"/api/public/rental-approvals/{raw_token}/")
        self.assertEqual(public_get.status_code, 200)
        self.assertEqual(public_get.data["rental_type"], "bulk")
        self.assertEqual(public_get.data["total_monthly_fee"], 4500)
        self.assertNotIn("phone", public_get.data["customer"])
        self.assertEqual(public_get["Cache-Control"], "no-store, private")
        self.assertEqual(public_get["Referrer-Policy"], "no-referrer")

        public_decision = public_client.post(
            f"/api/public/rental-approvals/{raw_token}/",
            {"decision": "approve", "consent": True},
            format="json",
        )
        self.assertEqual(public_decision.status_code, 200)
        self.rental.refresh_from_db()
        self.asset_one.refresh_from_db()
        self.asset_two.refresh_from_db()
        approval.refresh_from_db()

        self.assertEqual(approval.status, RentalApproval.APPROVED)
        self.assertEqual(self.rental.status, Rental.APPROVED)
        self.assertEqual(self.asset_one.status, RentalAsset.RENTED)
        self.assertEqual(self.asset_two.status, RentalAsset.RENTED)
        self.assertTrue(self.rental.events.filter(event_type=RentalEvent.APPROVAL_DECIDED).exists())

    def test_new_link_revokes_the_previous_pending_link(self):
        first, first_url = issue_approval_link(self.rental, self.user)
        second, _ = issue_approval_link(self.rental, self.user)
        first.refresh_from_db()

        self.assertEqual(first.status, RentalApproval.REVOKED)
        self.assertEqual(second.status, RentalApproval.PENDING)
        with self.assertRaises(RentalApprovalLinkGone):
            customer_decide(first_url.rsplit("/", 1)[-1], "approve", consent=True)

    def test_create_agreement_rechecks_asset_availability_and_cancel_releases_it(self):
        available = RentalAsset.objects.create(
            asset_tag="AST-TEST-3", serial_number="SERIAL-TEST-3", brand="HP", model_name="EliteBook"
        )
        response = self.client.post(
            "/api/rentals/create-agreement/",
            {
                "party": self.party.pk,
                "start": date.today().isoformat(),
                "tenure_months": 3,
                "lines": [{"asset_id": available.pk, "monthly_fee": 1800}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["rental_type"], "single")
        available.refresh_from_db()
        self.assertEqual(available.status, RentalAsset.RESERVED)

        duplicate = self.client.post(
            "/api/rentals/create-agreement/",
            {
                "party": self.party.pk,
                "start": date.today().isoformat(),
                "tenure_months": 3,
                "lines": [{"asset_id": available.pk, "monthly_fee": 1800}],
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)

        cancelled = self.client.post(
            f"/api/rentals/{response.data['id']}/cancel/",
            {"reason": "Customer cancelled before approval"},
            format="json",
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.data["status"], Rental.CANCELLED)
        available.refresh_from_db()
        self.assertEqual(available.status, RentalAsset.AVAILABLE)

    def test_approved_changes_require_reason_and_store_json_safe_audit(self):
        approval, approval_url = issue_approval_link(self.rental, self.user)
        customer_decide(approval_url.rsplit("/", 1)[-1], "approve", consent=True)

        without_reason = self.client.patch(
            f"/api/rentals/{self.rental.pk}/",
            {"start": "2030-01-02"},
            format="json",
        )
        self.assertEqual(without_reason.status_code, 400)

        changed = self.client.patch(
            f"/api/rentals/{self.rental.pk}/",
            {"start": "2030-01-02", "internal_change_reason": "Internal schedule correction"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)
        event = self.rental.events.get(event_type=RentalEvent.MODIFIED_AFTER_APPROVAL)
        self.assertEqual(event.metadata["before"]["start"], date.today().isoformat())
        self.assertEqual(event.metadata["after"]["start"], "2030-01-02")

    def test_assets_in_use_cannot_be_edited_or_hard_deleted(self):
        self.asset_one.status = RentalAsset.RESERVED
        self.asset_one.save(update_fields=["status"])
        edit = self.client.patch(
            f"/api/rental-assets/{self.asset_one.pk}/",
            {"model_name": "Changed model"},
            format="json",
        )
        self.assertEqual(edit.status_code, 400)
        delete = self.client.delete(f"/api/rental-assets/{self.asset_one.pk}/")
        self.assertEqual(delete.status_code, 400)

    def test_non_superuser_admin_can_approve_and_superuser_can_close(self):
        admin_user = get_user_model().objects.create_user(
            username="rental-role-admin",
            password="safe-test-password",
            role=Role.objects.get(slug="admin"),
        )
        admin_client = APIClient()
        admin_client.force_authenticate(admin_user)
        approved = admin_client.post(
            f"/api/rentals/{self.rental.pk}/approve-on-behalf/",
            {"reason": "Customer confirmed details in store"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data["approval_status"], RentalApproval.APPROVED)
        self.asset_one.refresh_from_db()
        self.assertEqual(self.asset_one.status, RentalAsset.RENTED)

        closed = self.client.post(
            f"/api/rentals/{self.rental.pk}/close/",
            {"reason": "Tenure completed and devices returned"},
            format="json",
        )
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.data["status"], Rental.CLOSED)
        self.asset_one.refresh_from_db()
        self.assertEqual(self.asset_one.status, RentalAsset.AVAILABLE)

import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from crmbook_backend.testing import client_for, complete_handover, make_user
from parties.models import Party
from rentals.models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalLine
from rentals.services import issue_approval_link

TEST_MEDIA = tempfile.mkdtemp(prefix="crmbook-change-request-media-")


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class RentalChangeRequestTests(TestCase):
    """Customer approve / reject / request-changes through the secure link."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        self.manager_user = make_user("rental-cr-manager", ["rentals.view", "rentals.manage"])
        self.manager = client_for(self.manager_user)
        self.party = Party.objects.create(name="Change Request Co", type=Party.RENTAL, phone="9876543210", joined=date.today())
        self.rental = self._rental("RNT-CR-1", "SN-CR-1")
        self.asset = self.rental.lines.get().asset
        self.public = APIClient()

    def _rental(self, code, serial):
        rental = Rental.objects.create(
            party=self.party, agreement_code=code, product_label="1 device", monthly_fee=2000,
            start=date.today(), tenure_months=6, last_payment=date.today(),
        )
        asset = RentalAsset.objects.create(asset_tag=f"AST-{serial}", serial_number=serial, brand="Dell",
                                           model_name="Latitude 5420", status=RentalAsset.RESERVED)
        complete_handover(RentalLine.objects.create(rental=rental, asset=asset, monthly_fee=2000), self.manager_user)
        return rental

    def link(self, rental=None):
        response = self.manager.post(f"/api/rentals/{(rental or self.rental).pk}/approval-link/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.data["approval_url"].rsplit("/", 1)[-1], response.data

    def decide(self, token, **body):
        return self.public.post(f"/api/public/rental-approvals/{token}/", body, format="json")

    def assert_undecided(self):
        self.rental.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(self.rental.status, Rental.PENDING_APPROVAL)
        self.assertEqual(self.asset.status, RentalAsset.RESERVED)

    # -- existing decisions keep working --------------------------------

    def test_approve_with_consent_still_rents_the_assets(self):
        token, _ = self.link()
        self.assertEqual(self.decide(token, decision="approve").status_code, 400)  # consent required
        response = self.decide(token, decision="approve", consent=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], RentalApproval.APPROVED)
        self.rental.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(self.rental.status, Rental.APPROVED)
        self.assertEqual(self.asset.status, RentalAsset.RENTED)

    def test_reject_still_releases_the_assets(self):
        token, _ = self.link()
        response = self.decide(token, decision="reject", reason="Too expensive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], RentalApproval.REJECTED)
        self.rental.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(self.rental.status, Rental.REJECTED)
        self.assertEqual(self.asset.status, RentalAsset.AVAILABLE)

    def test_link_response_reports_version_and_expiry(self):
        _, data = self.link()
        self.assertEqual(data["version"], 1)
        self.assertIsNotNone(data["expires_at"])
        self.assertEqual(data["rental"]["status"], Rental.PENDING_APPROVAL)

    # -- request changes: validation -------------------------------------

    def test_request_changes_requires_a_message(self):
        token, _ = self.link()
        self.assertEqual(self.decide(token, decision="request_changes").status_code, 400)
        self.assertEqual(self.decide(token, decision="request_changes", reason="").status_code, 400)
        self.assertEqual(RentalApproval.objects.get(rental=self.rental).status, RentalApproval.PENDING)

    def test_whitespace_only_message_is_rejected(self):
        token, _ = self.link()
        response = self.decide(token, decision="request_changes", reason="   \n\t  ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.data)
        self.assertFalse(self.rental.events.filter(event_type=RentalEvent.CHANGES_REQUESTED).exists())

    def test_message_over_500_characters_is_rejected(self):
        token, _ = self.link()
        self.assertEqual(self.decide(token, decision="request_changes", reason="x" * 501).status_code, 400)
        # 500 after trimming is fine
        ok = self.decide(token, decision="request_changes", reason="  " + "y" * 500 + "  ")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(len(RentalApproval.objects.get(rental=self.rental).reason), 500)

    # -- request changes: what it records and what it must NOT touch -----

    @mock.patch("rentals.services.notify_staff")
    def test_request_changes_is_recorded_on_the_right_approval_and_audit_event(self, notify):
        token, _ = self.link()
        response = self.public.post(
            f"/api/public/rental-approvals/{token}/",
            {"decision": "request_changes", "reason": "  Please add a second charger.  "},
            format="json", HTTP_USER_AGENT="TestPhone/1.0", REMOTE_ADDR="203.0.113.7",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["status"], RentalApproval.CHANGES_REQUESTED)
        self.assertEqual(response.data["change_request"], "Please add a second charger.")
        self.assertEqual(response["Cache-Control"], "no-store, private")

        approval = RentalApproval.objects.get(rental=self.rental)
        self.assertEqual(approval.status, RentalApproval.CHANGES_REQUESTED)
        self.assertEqual(approval.source, RentalApproval.CUSTOMER)
        self.assertEqual(approval.reason, "Please add a second charger.")
        self.assertIsNotNone(approval.decided_at)
        self.assertEqual(approval.decided_ip, "203.0.113.7")
        self.assertEqual(approval.decided_user_agent, "TestPhone/1.0")

        event = self.rental.events.get(event_type=RentalEvent.CHANGES_REQUESTED)
        self.assertEqual(event.approval, approval)
        self.assertIsNone(event.actor)
        self.assertEqual(event.metadata["message"], "Please add a second charger.")
        self.assertEqual(event.metadata["source"], RentalApproval.CUSTOMER)
        self.assertEqual(event.metadata["channel"], "secure_link")
        self.assertIn("requested_at", event.metadata)
        self.assertNotIn(token, str(event.metadata))
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], "rental_changes_requested")
        self.assertNotIn(token, str(notify.call_args))

    def test_request_changes_does_not_decide_the_agreement_or_move_assets(self):
        token, _ = self.link()
        self.assertEqual(self.decide(token, decision="request_changes", reason="Lower the rate").status_code, 200)
        self.assert_undecided()
        self.assertFalse(self.rental.events.filter(event_type=RentalEvent.APPROVAL_DECIDED).exists())
        self.assertFalse(RentalApproval.objects.filter(
            rental=self.rental, status__in=[RentalApproval.APPROVED, RentalApproval.REJECTED]).exists())

    def test_repeat_request_is_idempotent_and_the_link_takes_no_other_decision(self):
        token, _ = self.link()
        self.assertEqual(self.decide(token, decision="request_changes", reason="First request").status_code, 200)
        again = self.decide(token, decision="request_changes", reason="Second request")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["change_request"], "First request")
        self.assertEqual(self.rental.events.filter(event_type=RentalEvent.CHANGES_REQUESTED).count(), 1)

        self.assertEqual(self.decide(token, decision="approve", consent=True).status_code, 409)
        self.assertEqual(self.decide(token, decision="reject").status_code, 409)
        self.assert_undecided()

        # still viewable by the customer until it expires
        self.assertEqual(self.public.get(f"/api/public/rental-approvals/{token}/").status_code, 200)

    def test_new_link_answers_the_request_and_history_is_preserved(self):
        token, _ = self.link()
        self.decide(token, decision="request_changes", reason="Need 12 months")
        rental = self.manager.get(f"/api/rentals/{self.rental.pk}/").data
        self.assertEqual(rental["approval_status"], RentalApproval.CHANGES_REQUESTED)
        self.assertEqual(rental["open_change_request"]["message"], "Need 12 months")

        history = self.manager.get(f"/api/rentals/{self.rental.pk}/approval-history/").data
        self.assertEqual(history["open_change_request"]["version"], 1)
        self.assertTrue(history["approvals"][0]["change_request"]["open"])

        new_token, _ = self.link()
        first = RentalApproval.objects.get(rental=self.rental, version=1)
        self.assertEqual(first.status, RentalApproval.CHANGES_REQUESTED)  # not rewritten
        link_event = self.rental.events.filter(event_type=RentalEvent.APPROVAL_LINK_CREATED).last()
        self.assertEqual(link_event.metadata["responds_to_change_request_version"], 1)

        history = self.manager.get(f"/api/rentals/{self.rental.pk}/approval-history/").data
        self.assertIsNone(history["open_change_request"])
        v1 = next(a for a in history["approvals"] if a["version"] == 1)
        self.assertEqual(v1["change_request"], {"open": False, "answered_by_version": 2})
        types = [e["type"] for e in history["timeline"]]
        self.assertEqual(types.count(RentalEvent.APPROVAL_LINK_CREATED), 2)
        self.assertIn(RentalEvent.CHANGES_REQUESTED, types)
        self.assertNotIn("token_hash", str(history))

        # the revised link works normally
        self.assertEqual(self.decide(new_token, decision="approve", consent=True).status_code, 200)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, RentalAsset.RENTED)

    def test_cancelling_after_a_change_request_still_releases_assets(self):
        token, _ = self.link()
        self.decide(token, decision="request_changes", reason="Not now")
        response = self.manager.post(f"/api/rentals/{self.rental.pk}/cancel/", {"reason": "Customer withdrew"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["open_change_request"])
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, RentalAsset.AVAILABLE)

    # -- dead links ---------------------------------------------------------

    def test_expired_and_revoked_links_cannot_act(self):
        token, _ = self.link()
        RentalApproval.objects.filter(rental=self.rental).update(expires_at=timezone.now() - timedelta(minutes=1))
        for body in ({"decision": "request_changes", "reason": "x"}, {"decision": "approve", "consent": True}, {"decision": "reject"}):
            self.assertEqual(self.decide(token, **body).status_code, 410)
        self.assert_undecided()

        history = self.manager.get(f"/api/rentals/{self.rental.pk}/approval-history/").data
        self.assertIn("approval_link_expired", [e["type"] for e in history["timeline"]])

        revoked_token, _ = self.link()
        self.link()  # revokes the previous pending link
        self.assertEqual(self.decide(revoked_token, decision="request_changes", reason="x").status_code, 410)
        self.assertEqual(self.rental.events.filter(event_type=RentalEvent.CHANGES_REQUESTED).count(), 0)

    def test_finalized_approvals_cannot_be_changed_through_the_link(self):
        token, _ = self.link()
        self.decide(token, decision="approve", consent=True)
        self.assertEqual(self.decide(token, decision="request_changes", reason="Wait").status_code, 409)
        self.assertEqual(self.decide(token, decision="reject").status_code, 409)
        self.assertEqual(RentalApproval.objects.get(rental=self.rental).status, RentalApproval.APPROVED)

        other = self._rental("RNT-CR-2", "SN-CR-2")
        rejected_token, _ = self.link(other)
        self.decide(rejected_token, decision="reject")
        self.assertEqual(self.decide(rejected_token, decision="request_changes", reason="Wait").status_code, 409)
        self.assertEqual(other.approvals.get().status, RentalApproval.REJECTED)

    def test_invalid_token_and_unknown_decision(self):
        self.assertEqual(self.decide("not-a-real-token", decision="request_changes", reason="x").status_code, 404)
        token, _ = self.link()
        self.assertEqual(self.decide(token, decision="maybe").status_code, 400)

    # -- photos -------------------------------------------------------------

    def test_photos_are_limited_to_the_tokens_own_snapshot(self):
        token, _ = self.link()
        own_photo = self.rental.lines.get().photos.first()
        other = self._rental("RNT-CR-3", "SN-CR-3")
        issue_approval_link(other, self.manager_user)
        foreign_photo = other.lines.get().photos.first()

        url = f"/api/public/rental-approvals/{token}/photos/"
        self.assertEqual(self.public.get(f"{url}{own_photo.pk}/").status_code, 200)
        self.assertEqual(self.public.get(f"{url}{foreign_photo.pk}/").status_code, 404)

        # a photo added after the link was issued is not in its snapshot
        self.decide(token, decision="request_changes", reason="Show the charger")
        line = self.rental.lines.get()
        late = line.photos.create(kind="other", image=own_photo.image.name, content_type="image/jpeg")
        self.assertEqual(self.public.get(f"{url}{late.pk}/").status_code, 404)
        self.assertEqual(self.public.get(f"{url}{own_photo.pk}/").status_code, 200)

    def test_history_requires_rentals_view(self):
        outsider = client_for(make_user("rental-cr-outsider", ["repairs.view"]))
        self.assertEqual(outsider.get(f"/api/rentals/{self.rental.pk}/approval-history/").status_code, 403)

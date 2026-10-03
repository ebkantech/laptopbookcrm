import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from crmbook_backend.testing import FAKE_JPEG, client_for, complete_handover, make_user
from parties.models import Party
from rentals.models import Rental, RentalApproval, RentalAsset, RentalLine, RentalLinePhoto

TEST_MEDIA = tempfile.mkdtemp(prefix="crmbook-handover-media-")


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class DeviceHandoverTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        self.manager_user = make_user("rental-manager", ["rentals.view", "rentals.manage"])
        self.manager = client_for(self.manager_user)
        party = Party.objects.create(name="Handover Customer", type=Party.RENTAL, phone="9876543210", joined=date.today())
        self.rental = Rental.objects.create(
            party=party, agreement_code="RNT-HO-1", product_label="1 device", monthly_fee=2000,
            start=date.today(), tenure_months=6, last_payment=date.today(),
        )
        asset = RentalAsset.objects.create(asset_tag="AST-HO-1", serial_number="SN-HO-1", brand="Dell", model_name="Latitude 5420")
        self.line = RentalLine.objects.create(rental=self.rental, asset=asset, monthly_fee=2000)
        self.url = f"/api/rental-lines/{self.line.id}"

    def upload(self, kind, data=FAKE_JPEG, client=None):
        return (client or self.manager).post(
            f"{self.url}/photos/", {"kind": kind, "image": SimpleUploadedFile(f"{kind}.jpg", data, content_type="image/jpeg")},
            format="multipart",
        )

    def link(self):
        return self.manager.post(f"/api/rentals/{self.rental.id}/approval-link/")

    def test_approval_link_needs_a_complete_handover(self):
        response = self.link()
        self.assertEqual(response.status_code, 400)
        issues = response.json()["devices"]["AST-HO-1 (Dell Latitude 5420)"]
        self.assertTrue(any("Photos missing" in i for i in issues))
        self.assertTrue(any("working condition" in i for i in issues))

    def test_fill_in_handover_through_the_api(self):
        body = self.manager.get(f"{self.url}/handover/").json()
        self.assertEqual(len(body["meta"]["checks"]), len(RentalLine.CHECKS))
        self.assertTrue(body["editable"])

        response = self.manager.patch(f"{self.url}/handover/", {
            "checks": {key: True for key, _ in RentalLine.CHECKS},
            "working_confirmed": True,
            "condition_notes": "Light scratch on lid",
            "accessories": [{"name": "Charger", "serial": "CH-1"}, {"name": "Mouse"}],
            "warranty_included": True, "warranty_months": 6,
            "warranty_terms": "Hardware faults repaired or device swapped within 48 hours. Physical/liquid damage not covered.",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        issues = response.json()["issues"]
        self.assertTrue(any("Photos missing" in i for i in issues))
        self.assertTrue(any("accessories" in i for i in issues))

        for kind, _ in RentalLinePhoto.REQUIRED_KINDS:
            self.assertEqual(self.upload(kind).status_code, 201)
        self.assertEqual(self.upload(RentalLinePhoto.ACCESSORY).status_code, 201)
        self.assertEqual(self.manager.get(f"{self.url}/handover/").json()["issues"], [])
        self.line.refresh_from_db()
        self.assertEqual(self.line.handover_by, self.manager_user)

    def test_validation(self):
        bad = self.manager.patch(f"{self.url}/handover/", {"checks": {"teleporter": True}}, format="json")
        self.assertEqual(bad.status_code, 400)
        too_long = self.manager.patch(f"{self.url}/handover/", {"warranty_months": 7}, format="json")
        self.assertEqual(too_long.status_code, 400)
        no_terms = self.manager.patch(f"{self.url}/handover/", {"warranty_included": True}, format="json")
        self.assertTrue(any("warranty" in i for i in no_terms.json()["issues"]))

    def test_only_real_images_are_accepted(self):
        self.assertEqual(self.upload("front", data=b"<html>not a photo</html>").status_code, 400)
        self.assertEqual(self.upload("nonsense").status_code, 400)
        viewer = client_for(make_user("rental-viewer", ["rentals.view"]))
        self.assertEqual(self.upload("front", client=viewer).status_code, 403)

    def test_staff_can_view_photos_others_cannot(self):
        photo_id = self.upload("front").json()["id"]
        viewer = client_for(make_user("rental-viewer", ["rentals.view"]))
        response = viewer.get(f"/api/rental-photos/{photo_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(b"".join(response.streaming_content), FAKE_JPEG)
        self.assertEqual(client_for(make_user("no-rentals")).get(f"/api/rental-photos/{photo_id}/").status_code, 403)
        self.assertEqual(APIClient().get(f"/api/rental-photos/{photo_id}/").status_code, 401)

    def test_customer_sees_condition_photos_accessories_and_warranty(self):
        complete_handover(self.line, self.manager_user, accessories=[{"name": "Charger", "serial": "CH-1"}])
        RentalLine.objects.filter(pk=self.line.pk).update(warranty_included=True, warranty_terms="Swap within 48h.", warranty_months=6)
        response = self.link()
        self.assertEqual(response.status_code, 200, response.content)
        token = response.json()["approval_url"].rsplit("/", 1)[-1]

        public = APIClient().get(f"/api/public/rental-approvals/{token}/").json()
        item = public["items"][0]
        self.assertTrue(item["working_confirmed"])
        self.assertTrue(all(c["ok"] for c in item["checks"]))
        self.assertEqual(item["accessories"], [{"name": "Charger", "serial": "CH-1"}])
        self.assertEqual(item["warranty"], {"included": True, "months": 6, "terms": "Swap within 48h."})
        self.assertEqual(len(item["photos"]), 7)

        photo_id = item["photos"][0]["id"]
        self.assertEqual(APIClient().get(f"/api/public/rental-approvals/{token}/photos/{photo_id}/").status_code, 200)
        # a photo that isn't part of this approval isn't reachable through it
        other = Rental.objects.create(party=self.rental.party, product_label="x", monthly_fee=1, start=date.today(), tenure_months=1, last_payment=date.today())
        other_line = RentalLine.objects.create(rental=other, asset=RentalAsset.objects.create(asset_tag="AST-2", serial_number="SN-2", brand="HP", model_name="X"), monthly_fee=1)
        stranger = complete_handover(other_line).photos.first()
        self.assertEqual(APIClient().get(f"/api/public/rental-approvals/{token}/photos/{stranger.id}/").status_code, 404)

    def test_editing_after_link_sent_withdraws_the_link(self):
        complete_handover(self.line, self.manager_user)
        self.link()
        self.rental.refresh_from_db()
        self.assertEqual(self.rental.status, Rental.PENDING_APPROVAL)
        response = self.manager.patch(f"{self.url}/handover/", {"condition_notes": "New dent found"}, format="json")
        self.assertTrue(response.json()["approval_link_revoked"])
        self.rental.refresh_from_db()
        self.assertEqual(self.rental.status, Rental.DRAFT)
        self.assertFalse(self.rental.approvals.filter(status=RentalApproval.PENDING).exists())

    def test_handover_is_locked_once_approved(self):
        complete_handover(self.line, self.manager_user)
        Rental.objects.filter(pk=self.rental.pk).update(status=Rental.APPROVED)
        self.assertEqual(self.manager.patch(f"{self.url}/handover/", {"condition_notes": "x"}, format="json").status_code, 400)
        self.assertEqual(self.upload("front").status_code, 400)
        photo = self.line.photos.first()
        self.assertEqual(self.manager.delete(f"/api/rental-photos/{photo.id}/").status_code, 400)


class RentalAssetRegistrationTests(TestCase):
    def setUp(self):
        self.manager = client_for(make_user("asset-manager", ["rentals.view", "rentals.manage"]))
        self.existing = RentalAsset.objects.create(asset_tag="AST-0007", serial_number="5CD123ABC", brand="HP", model_name="EliteBook 840")

    def register(self, **data):
        return self.manager.post("/api/rental-assets/", {"brand": "Dell", "model_name": "Latitude", **data}, format="json")

    def test_blank_tag_is_generated(self):
        response = self.register(serial_number="NEW-SERIAL-1")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["asset_tag"], "AST-0008")

    def test_duplicate_tag_or_serial_explains_and_returns_the_existing_asset(self):
        dup_tag = self.register(asset_tag="ast-0007", serial_number="OTHER")
        self.assertEqual(dup_tag.status_code, 400)
        body = dup_tag.json()
        self.assertIn("pick it from the device list", body["asset_tag"][0])
        self.assertEqual(int(body["existing_asset"]["id"]), self.existing.id)  # DRF stringifies error values

        dup_serial = self.register(serial_number="5cd123abc")
        self.assertEqual(dup_serial.status_code, 400)
        self.assertIn("already registered", dup_serial.json()["serial_number"][0])

    def test_duplicate_of_rented_asset_names_the_agreement(self):
        party = Party.objects.create(name="X", type=Party.RENTAL, phone="9876543210", joined=date.today())
        rental = Rental.objects.create(party=party, agreement_code="RNT-000042", product_label="x", monthly_fee=1, start=date.today(), tenure_months=1, last_payment=date.today())
        RentalLine.objects.create(rental=rental, asset=self.existing, monthly_fee=1)
        RentalAsset.objects.filter(pk=self.existing.pk).update(status=RentalAsset.RENTED)
        response = self.register(asset_tag="AST-0007", serial_number="OTHER")
        self.assertIn("rented on agreement RNT-000042", response.json()["asset_tag"][0])

import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from crmbook_backend.testing import client_for, make_user
from .kyc import check_number, verhoeff_ok
from .models import Party, PartyIdDocument

VALID_AADHAAR = "234123412346"  # passes the Verhoeff check digit
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

TMP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP)
class CustomerIdTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.staff = client_for(make_user("rent", ["rentals.view", "rentals.manage", "parties.view"]))
        self.viewer = client_for(make_user("view", ["parties.view"]))
        self.admin = client_for(make_user("adm", ["parties.view", "parties.manage"]))
        self.party = Party.objects.create(name="Asha Rao", type=Party.RENTAL, phone="9876543210", joined=date.today())

    def add(self, client=None, fmt="json", **body):
        data = {"party": self.party.id, "id_type": "aadhaar", "number": VALID_AADHAAR, "consent": True, **body}
        return (client or self.staff).post("/api/party-ids/", data, format=fmt)

    def test_format_checks(self):
        self.assertTrue(verhoeff_ok(VALID_AADHAAR))
        self.assertFalse(verhoeff_ok("234123412345"))
        self.assertEqual(check_number("pan", "abcpe1234f")[0], "ABCPE1234F")
        self.assertIn("an individual", check_number("pan", "ABCPE1234F")[1])
        for t, bad in (("pan", "ABCDE12345"), ("pan", "ABCXE1234F"), ("aadhaar", "123412341234"), ("aadhaar", "234123412345"),
                       ("passport", "12345678"), ("voter_id", "AB1234567")):
            with self.assertRaises(Exception):
                check_number(t, bad)

    def test_aadhaar_is_stored_masked_with_consent_logged(self):
        self.assertEqual(self.add(consent=False).status_code, 400)
        r = self.add(number="2341 2341 2346")
        self.assertEqual(r.status_code, 201, r.content)
        doc = PartyIdDocument.objects.get()
        self.assertEqual((doc.number, doc.status), ("XXXX XXXX 2346", "format_ok"))
        self.assertFalse(PartyIdDocument.objects.filter(number__contains="23412341").exists())
        self.assertEqual(doc.consent_by.username, "rent")
        self.assertEqual(self.add(number="234123412345").status_code, 400)  # bad check digit

    def test_aadhaar_copy_must_be_confirmed_masked_and_is_staff_only(self):
        f = lambda: SimpleUploadedFile("aadhaar.png", PNG, content_type="image/png")
        self.assertEqual(self.add(fmt="multipart", file=f()).status_code, 400)
        r = self.add(fmt="multipart", file=f(), masked_copy="true")
        self.assertEqual(r.status_code, 201, r.content)
        url = f"/api/party-ids/{r.json()['id']}/file/"
        self.assertEqual(self.staff.get(url).status_code, 200)
        self.assertEqual(self.viewer.get(url).status_code, 403)
        bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        self.assertEqual(self.add(fmt="multipart", id_type="pan", number="ABCPE1234F", file=bad).status_code, 400)

    def test_verify_status_duplicates_and_permissions(self):
        self.assertEqual(self.add(client=self.viewer).status_code, 403)
        pan = self.add(id_type="pan", number="ABCPE1234F").json()
        other = Party.objects.create(name="Other", type=Party.RETAIL, phone="9876500000", joined=date.today())
        r = self.staff.post("/api/party-ids/", {"party": other.id, "id_type": "pan", "number": "ABCPE1234F", "consent": True}, format="json")
        self.assertIn("Asha Rao", r.json()["warning"])
        self.assertEqual(self.viewer.get(f"/api/party-ids/?party={self.party.id}").json()["status"], "unverified")
        url = f"/api/party-ids/{pan['id']}/verify/"
        self.assertEqual(self.staff.post(url, {"outcome": "failed"}, format="json").status_code, 400)  # reason required
        self.assertEqual(self.staff.post(url, {"outcome": "verified", "note": "Original PAN card seen"}, format="json").status_code, 200)
        listing = self.viewer.get(f"/api/party-ids/?party={self.party.id}").json()
        self.assertEqual(listing["status"], "verified")
        self.assertEqual(listing["documents"][0]["verified_by"], "rent")
        self.assertEqual(self.staff.delete(f"/api/party-ids/{pan['id']}/").status_code, 403)
        self.assertEqual(self.admin.delete(f"/api/party-ids/{pan['id']}/").status_code, 204)

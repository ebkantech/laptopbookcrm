"""Settings -> Business & messages: edit, validate, reset, and the fallbacks senders rely on."""
from django.test import TestCase, override_settings

from crmbook_backend.testing import client_for, make_user

from . import texts
from .models import MessageText
from .registry import BY_KEY, MESSAGES


@override_settings(BUSINESS_NAME="Royal Computer Solution", BUSINESS_PHONE="9811111111", BUSINESS_EMAIL="a@b.in")
class BrandingTests(TestCase):
    def setUp(self):
        self.owner = client_for(make_user("brand-owner", superuser=True))
        self.staff = client_for(make_user("brand-staff", perms=["inventory.view"]))

    def test_standard_wording_until_edited(self):
        self.assertEqual(texts.message("repair_ready", **self._samples("repair_ready")),
                         "Your Dell Latitude 5420 is ready! Please collect it from Karol Bagh Store.")
        data = self.owner.get("/api/branding/").json()
        self.assertTrue(data["can_edit"])
        self.assertEqual(len(data["messages"]), len(MESSAGES))
        self.assertFalse(any(m["edited"] for m in data["messages"]))
        self.assertEqual(data["effective"]["name"], "Royal Computer Solution")

    def test_edit_message_then_reset(self):
        key = "repair_ready"
        body = "Hi {device}, your device is ready at {business}."
        r = self.owner.post(f"/api/branding/messages/{key}/", {"body": body}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["edited"])
        sent = texts.message(key, **self._samples(key))
        self.assertTrue(sent.startswith("Hi "), sent)
        self.assertTrue(sent.endswith("Royal Computer Solution."), sent)
        self.assertEqual(self.owner.delete(f"/api/branding/messages/{key}/").status_code, 200)
        self.assertFalse(MessageText.objects.filter(key=key).exists())

    def test_unknown_placeholder_and_broken_braces_refused(self):
        r = self.owner.post("/api/branding/messages/repair_ready/", {"body": "Hi {nobody}"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unknown placeholder", str(r.json()["body"]))
        r = self.owner.post("/api/branding/messages/repair_ready/", {"body": "Hi {customer"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_required_placeholder(self):
        r = self.owner.post("/api/branding/messages/portal_code/", {"body": "Your code is ready."}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_bad_saved_text_falls_back_to_standard(self):
        MessageText.objects.create(key="repair_ready", body="Broken {oops")
        standard = texts.message("repair_ready", **self._samples("repair_ready"))
        self.assertNotIn("oops", standard)

    def test_staff_can_read_but_not_edit(self):
        self.assertEqual(self.staff.get("/api/branding/").status_code, 200)
        self.assertFalse(self.staff.get("/api/branding/").json()["can_edit"])
        self.assertEqual(self.staff.post("/api/branding/messages/repair_ready/", {"body": "x"}, format="json").status_code, 403)
        self.assertEqual(self.staff.patch("/api/branding/business/", {"name": "X"}, format="json").status_code, 403)

    def test_business_details_override_env(self):
        r = self.owner.patch("/api/branding/business/", {"name": "Royal Computers", "gstin": "07abcde1234f1z5",
                                                          "rental_terms": "One\n\n Two "}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        biz = texts.business()
        self.assertEqual(biz.name, "Royal Computers")
        self.assertEqual(biz.gstin, "07ABCDE1234F1Z5")
        self.assertEqual(biz.rental_terms, ["One", "Two"])
        self.assertEqual(biz.phone, "9811111111")  # blank -> .env
        self.assertEqual(self.owner.patch("/api/branding/business/", {"gstin": "123"}, format="json").status_code, 400)

    def test_preview(self):
        r = self.owner.post("/api/branding/messages/repair_ready/preview/", {"body": "Hi {device} from {business}"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Royal Computer Solution", r.json()["body"])
        self.assertNotIn("{", r.json()["body"])

    def test_every_standard_text_is_valid(self):
        for spec in MESSAGES:
            for part in ("subject", "body", "email_body"):
                if spec.get(part):
                    self.assertEqual(texts.problems(spec["key"], spec[part], required=spec.get("required", []) if part != "subject" else ()), [],
                                     f"{spec['key']}.{part}")

    def _samples(self, key):
        return {n: s for n, (_d, s) in BY_KEY[key]["placeholders"].items()}

"""Reading Cashfree's mobile-to-UPI lookup, and failing safe to a staff check."""
import os
from unittest import mock

from django.test import SimpleTestCase

from sales import payments


class CashfreeLookupTests(SimpleTestCase):
    def test_answers(self):
        read = payments._read_cashfree_lookup
        self.assertEqual(read({"status": "VALID", "vpa": "abc@okhdfc"}, "9876543210")["status"], payments.LINKED)
        self.assertEqual(read({"status": "SUCCESS", "vpa": None, "additional_vpas": ["x@ybl"]}, "9876543210")["status"], payments.LINKED)
        self.assertEqual(read({"status": "INVALID"}, "9876543210")["status"], payments.NOT_LINKED)
        self.assertEqual(read({"status": "PENDING"}, "9876543210")["status"], payments.UNKNOWN)

    @mock.patch.dict(os.environ, {"UPI_LOOKUP_PROVIDER": "cashfree", "CASHFREE_CLIENT_ID": "", "CASHFREE_CLIENT_SECRET": ""})
    def test_unconfigured_falls_back_to_staff_confirmation(self):
        self.assertEqual(payments.check_upi_linked("9876543210")["status"], payments.UNKNOWN)

    @mock.patch.dict(os.environ, {"UPI_LOOKUP_PROVIDER": "cashfree", "CASHFREE_CLIENT_ID": "id", "CASHFREE_CLIENT_SECRET": "secret"})
    def test_service_down_falls_back_to_staff_confirmation(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            result = payments.check_upi_linked("9876543210")
        self.assertEqual(result["status"], payments.UNKNOWN)
        self.assertIn("couldn't be reached", result["reason"])

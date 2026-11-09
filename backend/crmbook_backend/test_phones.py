from django.test import SimpleTestCase
from rest_framework.serializers import ValidationError

from crmbook_backend.phones import clean_customer_phone


class CustomerPhoneTests(SimpleTestCase):
    def test_indian_mobiles_are_stored_as_10_digits(self):
        for typed in ["9876543210", "98765 43210", "+91 98765 43210", "919876543210", "09876543210", "+91-98765-43210"]:
            self.assertEqual(clean_customer_phone(typed), "9876543210", typed)

    def test_foreign_numbers_need_a_plus(self):
        self.assertEqual(clean_customer_phone("+971 50 123 4567"), "+971501234567")
        self.assertEqual(clean_customer_phone("+1 (415) 555-0100"), "+14155550100")

    def test_refused(self):
        for typed in ["0050193876", "00919876543210", "12345", "98765432101234", "5876543210", "9999999999",
                      "98765abc10", "", "+0123456789"]:
            with self.assertRaises(ValidationError, msg=typed):
                clean_customer_phone(typed)

    def test_the_00_number_from_the_screenshot_explains_why(self):
        with self.assertRaises(ValidationError) as caught:
            clean_customer_phone("0050193876")
        self.assertIn("00", str(caught.exception.detail[0]))

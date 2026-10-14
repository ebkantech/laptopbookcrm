"""WhatsApp provider tests -- every Meta call is mocked; nothing is sent."""
import io
import logging
from contextlib import redirect_stdout
from unittest import mock

import requests
from django.test import SimpleTestCase

from crmbook_backend import notify

TOKEN = "EAAG-test-secret-token-do-not-leak"
META_ENV = {"WHATSAPP_PROVIDER": "meta_cloud", "WHATSAPP_PHONE_NUMBER_ID": "123456789012345", "WHATSAPP_ACCESS_TOKEN": TOKEN}
CLEAN = {key: "" for key in (
    "WHATSAPP_PROVIDER", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_GRAPH_API_VERSION",
    "WHATSAPP_DEFAULT_COUNTRY_CODE", "WHATSAPP_TEMPLATE_LANGUAGE", "WHATSAPP_TEMPLATE_RENTAL_APPROVAL",
    "WHATSAPP_TEMPLATE_RENTAL_APPROVAL_LANGUAGE",
)}


def meta_response(status=200, payload=None, json_error=False):
    resp = mock.Mock(status_code=status)
    if json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = payload if payload is not None else {}
    return resp


class WhatsAppTestBase(SimpleTestCase):
    def env(self, **values):
        patcher = mock.patch.dict("os.environ", {**CLEAN, **values})
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, to="9876543210", body="Hello", template=None, response=None, side_effect=None):
        """Send with requests.post mocked; returns (result, post_mock, captured log+stdout text)."""
        with mock.patch("requests.post", return_value=response, side_effect=side_effect) as post, \
                self.assertLogs("crmbook.notify", level="DEBUG") as logs, redirect_stdout(io.StringIO()) as out:
            logging.getLogger("crmbook.notify").debug("capture start")
            result = notify.send_whatsapp(to, body, template=template)
        return result, post, "\n".join(logs.output) + out.getvalue()


class ConsoleProviderTests(WhatsAppTestBase):
    def test_default_provider_is_simulated_and_sends_nothing(self):
        self.env()
        result, post, output = self.send()
        self.assertEqual(result["status"], "simulated")
        self.assertIsNone(result["provider_id"])
        post.assert_not_called()
        self.assertIn("simulated, no real send", output)

    def test_unknown_provider_falls_back_to_console(self):
        self.env(WHATSAPP_PROVIDER="twilio")
        result, post, _ = self.send()
        self.assertEqual(result["status"], "simulated")
        post.assert_not_called()

    def test_missing_phone_is_skipped(self):
        self.env(**META_ENV)
        result, post, _ = self.send(to="")
        self.assertEqual(result["status"], "skipped")
        post.assert_not_called()

    def test_console_number_check_is_still_a_plausibility_check(self):
        self.env()
        self.assertTrue(notify.check_whatsapp_number("9876543210")["has_whatsapp"])
        self.assertFalse(notify.check_whatsapp_number("12345")["has_whatsapp"])


class MetaConfigurationTests(WhatsAppTestBase):
    def test_missing_phone_number_id(self):
        self.env(**{**META_ENV, "WHATSAPP_PHONE_NUMBER_ID": ""})
        result, post, _ = self.send()
        self.assertEqual((result["status"], result["error_code"]), ("failed", "config_missing"))
        self.assertIn("WHATSAPP_PHONE_NUMBER_ID", result["reason"])
        post.assert_not_called()

    def test_missing_access_token(self):
        self.env(**{**META_ENV, "WHATSAPP_ACCESS_TOKEN": ""})
        result, post, _ = self.send()
        self.assertEqual((result["status"], result["error_code"]), ("failed", "config_missing"))
        self.assertIn("WHATSAPP_ACCESS_TOKEN", result["reason"])
        post.assert_not_called()

    def test_non_numeric_phone_number_id(self):
        self.env(**{**META_ENV, "WHATSAPP_PHONE_NUMBER_ID": "my-number"})
        result, post, _ = self.send()
        self.assertEqual(result["error_code"], "config_invalid")
        post.assert_not_called()

    def test_invalid_recipient_is_not_sent(self):
        self.env(**META_ENV)
        result, post, _ = self.send(to="12-34")
        self.assertEqual((result["status"], result["error_code"]), ("failed", "invalid_number"))
        post.assert_not_called()

    def test_number_check_does_not_call_the_retired_contacts_endpoint(self):
        self.env(**META_ENV)
        with mock.patch("requests.post") as post:
            result = notify.check_whatsapp_number("9876543210")
        post.assert_not_called()
        self.assertEqual((result["has_whatsapp"], result["checked"]), (None, False))


class NormalizationTests(SimpleTestCase):
    def test_numbers_become_digits_with_country_code(self):
        with mock.patch.dict("os.environ", CLEAN):
            cases = {
                "9876543210": "919876543210",
                "+91 98765-43210": "919876543210",
                "09876543210": "919876543210",
                "0091 98765 43210": "919876543210",
                "+1 (415) 555-0100": "14155550100",
                "12345": "",
                "": "",
                None: "",
            }
            for raw, expected in cases.items():
                self.assertEqual(notify.normalize_whatsapp_number(raw), expected, raw)

    def test_default_country_code_is_configurable(self):
        with mock.patch.dict("os.environ", {**CLEAN, "WHATSAPP_DEFAULT_COUNTRY_CODE": "44"}):
            self.assertEqual(notify.normalize_whatsapp_number("7911123456"), "447911123456")


class MetaSendTests(WhatsAppTestBase):
    def setUp(self):
        self.env(**META_ENV)

    def test_accepted_message_returns_provider_id(self):
        result, post, output = self.send(
            to="+91 98765 43210", body="Your link",
            response=meta_response(200, {"messaging_product": "whatsapp", "contacts": [{"wa_id": "919876543210"}], "messages": [{"id": "wamid.ABC"}]}),
        )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["provider_id"], "wamid.ABC")
        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertEqual(url, f"https://graph.facebook.com/{notify.GRAPH_API_VERSION_DEFAULT}/123456789012345/messages")
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(kwargs["json"]["to"], "919876543210")
        self.assertEqual(kwargs["json"]["type"], "text")
        self.assertEqual(kwargs["json"]["text"]["body"], "Your link")
        self.assertTrue(kwargs["timeout"])
        self.assertNotIn(TOKEN, output)

    def test_api_version_is_configurable(self):
        self.env(**META_ENV, WHATSAPP_GRAPH_API_VERSION="v26.0")
        _, post, _ = self.send(response=meta_response(200, {"messages": [{"id": "wamid.1"}]}))
        self.assertIn("/v26.0/", post.call_args.args[0])

    def test_template_is_sent_instead_of_free_text(self):
        template = {"name": "rental_approval_link", "language": "en_US", "params": ["Akif", "RNT-1", "https://x/y\nz"]}
        result, post, _ = self.send(template=template, response=meta_response(200, {"messages": [{"id": "wamid.T"}]}))
        self.assertEqual((result["status"], result["kind"]), ("sent", "template"))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["type"], "template")
        self.assertNotIn("text", payload)
        self.assertEqual(payload["template"]["name"], "rental_approval_link")
        self.assertEqual(payload["template"]["language"], {"code": "en_US"})
        params = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
        self.assertEqual(params, ["Akif", "RNT-1", "https://x/y z"])  # no newlines -- Meta rejects them

    def test_template_without_params_has_no_components(self):
        _, post, _ = self.send(template={"name": "hello_world", "language": "en_US", "params": []},
                               response=meta_response(200, {"messages": [{"id": "wamid.H"}]}))
        self.assertNotIn("components", post.call_args.kwargs["json"]["template"])

    def test_rejection_is_reported_as_failed_with_a_useful_reason(self):
        result, _, output = self.send(response=meta_response(400, {"error": {
            "message": "(#131030) Recipient phone number not in allowed list", "type": "OAuthException",
            "code": 131030, "fbtrace_id": "TRACE1"}}))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["provider_id"])
        self.assertEqual(result["error_code"], "meta_131030")
        self.assertIn("allowed recipient list", result["reason"])
        self.assertIn("TRACE1", output)

    def test_outside_24h_window_points_at_templates(self):
        result, _, _ = self.send(response=meta_response(400, {"error": {"code": 131047, "message": "Re-engagement message"}}))
        self.assertEqual(result["error_code"], "meta_131047")
        self.assertIn("template", result["reason"])

    def test_expired_token_never_leaks_the_token(self):
        result, _, output = self.send(response=meta_response(401, {"error": {
            "message": f"Error validating access token {TOKEN}: Session has expired", "code": 190, "error_subcode": 463}}))
        self.assertEqual(result["error_code"], "meta_190")
        self.assertIn("expired", result["reason"])
        self.assertNotIn(TOKEN, str(result))
        self.assertNotIn(TOKEN, output)

    def test_unknown_error_message_is_redacted(self):
        result, _, output = self.send(response=meta_response(400, {"error": {"code": 999999, "message": f"weird {TOKEN}"}}))
        self.assertEqual(result["status"], "failed")
        self.assertNotIn(TOKEN, str(result))
        self.assertNotIn(TOKEN, output)

    def test_rate_limit(self):
        result, _, _ = self.send(response=meta_response(429, {"error": {"code": 130429, "message": "Rate limit hit"}}))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "meta_130429"))
        self.assertIn("retry", result["reason"])

    def test_timeout(self):
        result, _, output = self.send(side_effect=requests.Timeout("read timed out"))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "timeout"))
        self.assertNotIn(TOKEN, output)

    def test_network_failure(self):
        result, _, _ = self.send(side_effect=requests.ConnectionError("no route"))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "network_error"))

    def test_non_json_response_is_not_a_success(self):
        result, _, _ = self.send(response=meta_response(200, json_error=True))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "malformed_response"))
        self.assertIsNone(result["provider_id"])

    def test_success_status_without_message_id_is_not_a_success(self):
        for payload in ({}, {"messages": []}, {"messages": "x"}, [1, 2]):
            result, _, _ = self.send(response=meta_response(200, payload))
            self.assertEqual(result["status"], "failed", payload)

    def test_non_json_error_response(self):
        result, _, _ = self.send(response=meta_response(502, json_error=True))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "http_502"))

    def test_unexpected_exception_never_raises(self):
        result, _, output = self.send(side_effect=RuntimeError(f"boom {TOKEN}"))
        self.assertEqual((result["status"], result["error_code"]), ("failed", "unexpected"))
        self.assertNotIn(TOKEN, output)

    def test_unexpected_exception_is_logged_by_class_and_location_only(self):
        result, _, output = self.send(side_effect=UnicodeEncodeError("latin-1", TOKEN, 0, 1, "boom"))
        self.assertIn("UnicodeEncodeError", result["reason"])
        self.assertIn("builtins.UnicodeEncodeError", output)
        self.assertIn("notify.py:", output)
        self.assertNotIn(TOKEN, output)
        self.assertNotIn(TOKEN, result["reason"])

    def test_token_with_pasted_quotes_or_ellipsis_fails_before_sending(self):
        # the real crash: http.client can't latin-1 encode these into the
        # Authorization header and raises UnicodeEncodeError
        for bad in (f"“{TOKEN}”", f"{TOKEN}…", f"{TOKEN} x", f"'{TOKEN}'"):
            self.env(**{**META_ENV, "WHATSAPP_ACCESS_TOKEN": bad})
            result, post, output = self.send()
            post.assert_not_called()
            self.assertEqual((result["status"], result["error_code"]), ("failed", "config_invalid"), bad)
            self.assertIn("WHATSAPP_ACCESS_TOKEN", result["reason"])
            self.assertNotIn(TOKEN, result["reason"] + output)

    def test_existing_callers_return_shape(self):
        """Callers read result["status"] and result.get("provider_id")."""
        for kwargs in ({"response": meta_response(200, {"messages": [{"id": "wamid.1"}]})},
                       {"response": meta_response(400, {"error": {"code": 100}})},
                       {"side_effect": requests.Timeout()}):
            result, _, _ = self.send(**kwargs)
            self.assertIn(result["status"], ("sent", "simulated", "skipped", "failed"))
            self.assertIn("provider_id", result)


class TemplateConfigTests(SimpleTestCase):
    def test_no_template_configured(self):
        with mock.patch.dict("os.environ", CLEAN):
            self.assertIsNone(notify.whatsapp_template("rental_approval", ["a"]))

    def test_template_and_language_from_environment(self):
        env = {**CLEAN, "WHATSAPP_TEMPLATE_RENTAL_APPROVAL": "rental_link", "WHATSAPP_TEMPLATE_LANGUAGE": "en_US"}
        with mock.patch.dict("os.environ", env):
            self.assertEqual(notify.whatsapp_template("rental_approval", ["A", 2]),
                             {"name": "rental_link", "language": "en_US", "params": ["A", "2"]})
        env["WHATSAPP_TEMPLATE_RENTAL_APPROVAL_LANGUAGE"] = "hi"
        with mock.patch.dict("os.environ", env):
            self.assertEqual(notify.whatsapp_template("rental_approval", [])["language"], "hi")

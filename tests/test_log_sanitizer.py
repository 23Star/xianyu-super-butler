import unittest

from utils.log_sanitizer import REDACTED, redact_sensitive_text


class LogSanitizerTests(unittest.TestCase):
    def test_redacts_cookie_pairs_and_authorization(self):
        message = (
            "_m_h5_tk=secret_value; cookie2=another_secret; "
            "Authorization: Bearer bearer_secret"
        )
        redacted = redact_sensitive_text(message)
        self.assertNotIn("secret_value", redacted)
        self.assertNotIn("another_secret", redacted)
        self.assertNotIn("bearer_secret", redacted)
        self.assertGreaterEqual(redacted.count(REDACTED), 3)

    def test_redacts_dict_and_json_values(self):
        message = (
            "{'accessToken': 'token-value', \"sign\": \"signature-value\", "
            "'sgcookie': 'cookie-value'}"
        )
        redacted = redact_sensitive_text(message)
        self.assertNotIn("token-value", redacted)
        self.assertNotIn("signature-value", redacted)
        self.assertNotIn("cookie-value", redacted)

    def test_keeps_non_sensitive_diagnostics(self):
        message = "status=200 cookie_fields=18 payload_length=42"
        self.assertEqual(redact_sensitive_text(message), message)


if __name__ == "__main__":
    unittest.main()

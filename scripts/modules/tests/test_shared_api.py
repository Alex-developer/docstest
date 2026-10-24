"""Run with: venv/bin/python -m unittest discover -s scripts/modules/tests -v"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import allsky_shared


class APIErrorTests(unittest.TestCase):
    def setUp(self):
        url_patch = patch.object(allsky_shared, "get_api_url", return_value="http://localhost:8090")
        url_patch.start()
        self.addCleanup(url_patch.stop)
        post_patch = patch.object(allsky_shared.requests, "post")
        self.post = post_patch.start()
        self.addCleanup(post_patch.stop)
        self.http_methods = {"post": self.post}
        for method in ("get", "put", "delete"):
            method_patch = patch.object(allsky_shared.requests, method)
            self.http_methods[method] = method_patch.start()
            self.addCleanup(method_patch.stop)

    def response(self, status, body):
        response = requests.Response()
        response.status_code = status
        response.url = "http://localhost:8090/gpio/pwm"
        response.request = requests.Request("POST", response.url).prepare()
        response._content = body.encode()
        for method in self.http_methods.values():
            method.return_value = response
        return response

    def api_calls(self):
        return (
            ("read_gpio_pin", lambda: allsky_shared.read_gpio_pin(18), True),
            ("get_gpio_pin", lambda: allsky_shared.get_gpio_pin(18), True),
            ("set_gpio_pin", lambda: allsky_shared.set_gpio_pin(18, True, "Dew"), self.success_data),
            ("set_pwm", lambda: allsky_shared.set_pwm(18, 32768, "Dew"), self.success_data),
            ("stop_pwm", lambda: allsky_shared.stop_pwm(18), self.success_data),
            ("configure_tacho", lambda: allsky_shared.configure_tacho("fan", 18), self.success_data),
            ("read_tacho", lambda: allsky_shared.read_tacho("fan"), self.success_data),
            ("get_tacho_speed", lambda: allsky_shared.get_tacho_speed("fan"), 123.0),
            ("get_tacho_speed_configure", lambda: allsky_shared.get_tacho_speed("fan", 18), 123.0),
            ("stop_tacho", lambda: allsky_shared.stop_tacho("fan"), self.success_data),
        )

    success_data = {"pin": "18", "value": "on", "rpm": 123}

    def call_pwm(self, stop=False):
        if stop:
            return allsky_shared.stop_pwm(18)
        return allsky_shared.set_pwm(18, 32768, "Dew")

    def test_conflict_message_reaches_existing_exception_logging(self):
        error = "GPIO pin 18 is reserved: GPIO line is claimed"
        for stop in (False, True):
            with self.subTest(stop=stop):
                response = self.response(409, json.dumps({
                    "error": error, "pin": "18", "reason": "GPIO line is claimed"
                }))
                with self.assertRaises(requests.HTTPError) as caught:
                    self.call_pwm(stop)
                self.assertEqual(str(caught.exception), error)
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(str(caught.exception).count("GPIO line is claimed"), 1)
                self.assertIs(caught.exception.response, response)
                self.assertIs(caught.exception.request, response.request)

    def test_backend_error_includes_detailed_message(self):
        self.response(503, json.dumps({
            "error": "GPIO backend unavailable",
            "message": "Unable to determine GPIO 18 function: pinctrl unavailable",
        }))
        with self.assertRaises(requests.HTTPError) as caught:
            self.call_pwm()
        self.assertEqual(
            str(caught.exception),
            "GPIO backend unavailable; Unable to determine GPIO 18 function: pinctrl unavailable",
        )

    def test_unusable_error_body_preserves_original_http_error(self):
        for body in ("<html>Bad Gateway</html>", "[]", '"error"', '{"error": null}'):
            with self.subTest(body=body):
                response = self.response(502, body)
                with self.assertRaises(requests.HTTPError) as expected:
                    response.raise_for_status()
                with self.assertRaises(requests.HTTPError) as caught:
                    self.call_pwm()
                self.assertEqual(str(caught.exception), str(expected.exception))
                self.assertIs(caught.exception.response, response)

    def test_successful_pwm_responses_are_unchanged(self):
        for stop in (False, True):
            with self.subTest(stop=stop):
                data = {"pin": "18", "frequency": 1000, "duty": 0 if stop else 32768}
                self.response(200, json.dumps(data))
                self.assertEqual(self.call_pwm(stop), data)

    def test_all_api_helpers_include_server_errors(self):
        for name, call, _ in self.api_calls():
            for status in (400, 409, 500, 503):
                with self.subTest(helper=name, status=status):
                    response = self.response(status, json.dumps({
                        "error": "GPIO operation failed",
                        "message": "Unable to access GPIO 18",
                        "reason": "GPIO line is claimed",
                    }))
                    with self.assertRaises(requests.HTTPError) as caught:
                        call()
                    self.assertEqual(
                        str(caught.exception),
                        "GPIO operation failed; Unable to access GPIO 18; GPIO line is claimed",
                    )
                    self.assertIs(caught.exception.response, response)

    def test_all_api_helpers_preserve_successful_return_values(self):
        for name, call, expected in self.api_calls():
            with self.subTest(helper=name):
                self.response(200, json.dumps(self.success_data))
                self.assertEqual(call(), expected)

    def test_all_api_helpers_preserve_connection_errors(self):
        error = requests.ConnectionError("Connection refused")
        for method in self.http_methods.values():
            method.side_effect = error
        for name, call, _ in self.api_calls():
            with self.subTest(helper=name):
                with self.assertRaises(requests.ConnectionError) as caught:
                    call()
                self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()

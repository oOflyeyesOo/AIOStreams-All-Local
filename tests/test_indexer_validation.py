import io
import http.server
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request
from tools.indexer_validation import validate_indexer, NoIndexerRedirects


class IndexerValidationTests(unittest.TestCase):
    settings = {"NZB_INDEXER_URL": "https://indexer.fixture/base", "NZB_INDEXER_API_KEY": "private-fixture"}

    def test_saved_keys_never_follow_unmatched_endpoints(self):
        for url in ("https://other.fixture", "http://indexer.fixture/base",
                    "https://sub.indexer.fixture/base", "https://indexer.fixture/other",
                    "https://indexer.fixture:8443/base"):
            with self.subTest(url=url), patch("tools.indexer_validation.OPENER.open") as opened:
                result = validate_indexer(self.settings, "saved", url)
                self.assertEqual(result["status"], "invalid")
                opened.assert_not_called()

    def test_id_does_not_override_url_binding(self):
        settings = {"USENET_EXTRA_INDEXERS": [{"id": "one", "url": "https://one.fixture", "apiKey": "private"}]}
        with patch("tools.indexer_validation.OPENER.open") as opened:
            self.assertEqual(validate_indexer(settings, "saved", "https://other.fixture", "one")["status"], "invalid")
            opened.assert_not_called()

    def test_equivalent_api_endpoint_and_xml_caps(self):
        with patch("tools.indexer_validation.OPENER.open", return_value=io.BytesIO(b"<caps><searching/></caps>")) as opened:
            result = validate_indexer(self.settings, "saved", "https://INDEXER.fixture:443/base/api/")
        self.assertEqual(result["status"], "valid")
        self.assertIn("authorization has not been tested", result["detail"])
        self.assertEqual(opened.call_args.args[0].full_url, "https://indexer.fixture/base/api?t=caps&apikey=private-fixture")

    def test_html_errors_and_oversized_responses_are_not_valid(self):
        for body in (b"<html>Login</html>", b'<error description="private-fixture"/>',
                     b"not xml", b"x" * 1048577, b'<!DOCTYPE caps><caps/>'):
            with self.subTest(body=body[:30]), patch("tools.indexer_validation.OPENER.open", return_value=io.BytesIO(body)):
                result = validate_indexer(self.settings)
                self.assertNotEqual(result["status"], "valid")
                self.assertNotIn("private-fixture", result["detail"])

    def test_redirect_handler_never_forwards_request(self):
        handler = NoIndexerRedirects()
        for target in ("https://other.fixture/api", "https://indexer.fixture/moved"):
            self.assertIsNone(handler.redirect_request(
                Request("https://indexer.fixture/api?apikey=private"), None, 302, "", {}, target))

    def test_actual_http_redirect_does_not_reach_destination(self):
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/stolen?apikey=private-fixture")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = validate_indexer({}, "private-fixture", f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(result["status"], "rejected")
            self.assertIn("redirected", result["detail"])
            self.assertEqual(len(requests), 1)
            self.assertTrue(requests[0].startswith("/api?"))
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

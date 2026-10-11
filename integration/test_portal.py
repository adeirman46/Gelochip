"""HTTP smoke tests without EDA, LLM, or third-party dependencies."""
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import portal


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = portal.ThreadingHTTPServer(("127.0.0.1", 0), portal.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_portal_has_all_three_apps(self):
        with urllib.request.urlopen(self.url) as response:
            page = response.read().decode()
        for url, _ in portal.SERVICES.values():
            self.assertIn(url, page)

    def test_status_endpoint(self):
        def fake_check(item):
            name, (url, _) = item
            return name, {"url": url, "running": name == "anoa"}
        with patch.object(portal, "check_service", fake_check):
            with urllib.request.urlopen(self.url + "/api/services") as response:
                payload = json.load(response)
        self.assertEqual(set(payload), set(portal.SERVICES))
        self.assertTrue(payload["anoa"]["running"])
        self.assertFalse(payload["panda"]["running"])

    def test_unknown_path_cannot_read_workspace_files(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.url + "/../info.yaml")
        self.assertEqual(error.exception.code, 404)

    def test_unreachable_service(self):
        with patch.object(portal.urllib.request, "urlopen", side_effect=OSError("offline")):
            _, status = portal.check_service(("test", ("http://localhost", "http://localhost")))
        self.assertFalse(status["running"])


if __name__ == "__main__":
    unittest.main()

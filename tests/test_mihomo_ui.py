import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from u20vpn.mihomo import render_config
from u20vpn.mihomo_ui import MihomoController, build_handler, normalize_controller_url, read_controller_config


class MihomoUiTests(unittest.TestCase):
    def test_read_controller_config_from_generated_yaml(self):
        config = render_config(
            "https://example.com/sub?token=abc",
            controller="127.0.0.1:9090",
            controller_secret="secret-value",
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(config, encoding="utf-8")

            controller, secret = read_controller_config(str(path))

        self.assertEqual(controller, "127.0.0.1:9090")
        self.assertEqual(secret, "secret-value")

    def test_normalize_controller_url_uses_localhost_for_wildcard(self):
        self.assertEqual(normalize_controller_url("0.0.0.0:9090"), "http://127.0.0.1:9090")
        self.assertEqual(normalize_controller_url(":9090"), "http://127.0.0.1:9090")

    def test_controller_filters_proxy_groups(self):
        controller = MihomoController("http://127.0.0.1:9090")
        controller.request_json = lambda *_args, **_kwargs: {
            "proxies": {
                "DIRECT": {"type": "Direct"},
                "PROXY": {"type": "Selector", "now": "node-a", "all": ["node-a", "node-b"]},
                "AUTO": {"type": "URLTest", "now": "node-b", "all": ["node-a", "node-b"]},
            }
        }

        data = controller.proxies()

        self.assertEqual([group["name"] for group in data["groups"]], ["PROXY", "AUTO"])

    def test_ui_proxy_endpoints_against_fake_controller(self):
        fake_controller = ThreadingHTTPServer(("127.0.0.1", 0), FakeMihomoHandler)
        fake_url = f"http://127.0.0.1:{fake_controller.server_port}"
        ui = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(MihomoController(fake_url, "test-secret")))
        ui_url = f"http://127.0.0.1:{ui.server_port}"

        try:
            import threading

            fake_thread = threading.Thread(target=fake_controller.serve_forever, daemon=True)
            ui_thread = threading.Thread(target=ui.serve_forever, daemon=True)
            fake_thread.start()
            ui_thread.start()

            html = urlopen(f"{ui_url}/", timeout=5).read().decode("utf-8")
            proxies = urlopen(f"{ui_url}/api/proxies", timeout=5).read().decode("utf-8")
            request = Request(
                f"{ui_url}/api/groups/PROXY",
                data=b'{"name":"node-b"}',
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            selected = urlopen(request, timeout=5).read().decode("utf-8")

            self.assertIn("mihomo 控制台", html)
            self.assertIn("node-a", proxies)
            self.assertIn("ok", selected)
            self.assertEqual(FakeMihomoHandler.last_authorization, "Bearer test-secret")
            self.assertEqual(FakeMihomoHandler.last_selection, "node-b")
        finally:
            ui.shutdown()
            fake_controller.shutdown()
            ui.server_close()
            fake_controller.server_close()


class FakeMihomoHandler(BaseHTTPRequestHandler):
    last_authorization = None
    last_selection = None

    def do_GET(self):
        self.last_authorization = self.headers.get("Authorization")
        FakeMihomoHandler.last_authorization = self.last_authorization
        if self.path == "/version":
            self.write_json({"version": "fake"})
            return
        if self.path == "/proxies":
            self.write_json(
                {
                    "proxies": {
                        "PROXY": {"type": "Selector", "now": "node-a", "all": ["node-a", "node-b"]},
                        "node-a": {"type": "Vless", "history": [{"delay": 120}]},
                        "node-b": {"type": "Trojan", "history": [{"delay": 260}]},
                    }
                }
            )
            return
        if self.path.startswith("/proxies/node-a/delay"):
            self.write_json({"delay": 120})
            return
        self.send_error(404)

    def do_PUT(self):
        if self.path == "/proxies/PROXY":
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            FakeMihomoHandler.last_selection = raw.decode("utf-8").split('"')[3]
            self.write_json({"ok": True})
            return
        self.send_error(404)

    def write_json(self, data):
        import json

        raw = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, _format, *_args):
        return


if __name__ == "__main__":
    unittest.main()

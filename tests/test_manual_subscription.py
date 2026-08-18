import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manual-subscription-to-singbox.py"


def load_module():
    spec = importlib.util.spec_from_file_location("manual_subscription_to_singbox", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = load_module()

ANYTLS_LINE = (
    "  - { name: 日本01, type: anytls, server: us-cn2.dnsefan04851.com, port: 5771,"
    ' password: b3d4d5c3-84e0-4a4f-895c-791a05e7870a, client-fingerprint: chrome,'
    ' udp: true, alpn: [h2, http/1.1], sni: dldir1v6.qq.com, skip-cert-verify: true }'
)


class ManualSubscriptionTests(unittest.TestCase):
    def test_parse_node_line(self):
        node = mod.parse_node_line(ANYTLS_LINE)
        self.assertEqual(node["name"], "日本01")
        self.assertEqual(node["type"], "anytls")
        self.assertEqual(node["server"], "us-cn2.dnsefan04851.com")
        self.assertEqual(node["port"], "5771")

    def test_parse_ignores_non_node_lines(self):
        self.assertIsNone(mod.parse_node_line("proxies:"))
        self.assertIsNone(mod.parse_node_line("  - name: group"))

    def test_build_anytls_outbound(self):
        node = mod.parse_node_line(ANYTLS_LINE)
        out = mod.build_outbound(node)
        self.assertIsNotNone(out)
        self.assertEqual(out["type"], "anytls")
        self.assertEqual(out["tag"], "日本01")
        self.assertEqual(out["server"], "us-cn2.dnsefan04851.com")
        self.assertEqual(out["server_port"], 5771)
        self.assertEqual(out["password"], "b3d4d5c3-84e0-4a4f-895c-791a05e7870a")
        tls = out["tls"]
        self.assertTrue(tls["enabled"])
        self.assertEqual(tls["server_name"], "dldir1v6.qq.com")
        self.assertTrue(tls["insecure"])
        self.assertEqual(tls["utls"], {"enabled": True, "fingerprint": "chrome"})

    def test_build_skips_unsupported_type(self):
        node = {
            "name": "x",
            "type": "ssr",
            "server": "example.com",
            "port": "443",
            "password": "p",
        }
        self.assertIsNone(mod.build_outbound(node))

    def test_build_rejects_missing_fields(self):
        self.assertIsNone(mod.build_outbound({"name": "", "type": "anytls", "server": "a", "port": "1"}))


if __name__ == "__main__":
    unittest.main()

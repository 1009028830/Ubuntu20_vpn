import unittest

from u20vpn.mihomo import normalize_subscription_url, render_config, render_systemd_service


class MihomoConfigTests(unittest.TestCase):
    def test_render_config_uses_proxy_provider(self):
        config = render_config("https://example.com/sub?token=abc", controller_secret="secret")

        self.assertIn("proxy-providers:", config)
        self.assertIn("type: http", config)
        self.assertIn('"https://example.com/sub?token=abc"', config)
        self.assertIn("tun:", config)
        self.assertIn("auto-route: true", config)
        self.assertNotIn("GEOIP", config)

    def test_clash_install_url_is_unwrapped(self):
        url = normalize_subscription_url("clash://install-config?url=https%3A%2F%2Fexample.com%2Fsub%3Ftoken%3Dabc")

        self.assertEqual(url, "https://example.com/sub?token=abc")

    def test_single_node_uri_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_subscription_url("vless://example")

    def test_render_systemd_service(self):
        service = render_systemd_service("/etc/mihomo", "/usr/local/bin/mihomo")

        self.assertIn("ExecStart=/usr/local/bin/mihomo -d /etc/mihomo", service)
        self.assertIn("CAP_NET_ADMIN", service)


if __name__ == "__main__":
    unittest.main()

import io
import unittest
from contextlib import redirect_stdout

from u20vpn.cli import main
from u20vpn.crypto import load_secret


class CliTests(unittest.TestCase):
    def test_gen_key_does_not_require_linux_tun(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            code = main(["gen-key"])

        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(load_secret(stdout.getvalue())), 32)

    def test_clash_render_config_does_not_require_linux_tun(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            code = main(["clash", "render-config", "--subscription-url", "https://example.com/sub?token=abc"])

        self.assertEqual(code, 0)
        self.assertIn("proxy-providers:", stdout.getvalue())
        self.assertIn("https://example.com/sub?token=abc", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

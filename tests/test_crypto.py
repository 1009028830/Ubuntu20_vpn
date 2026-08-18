import unittest

from u20vpn.crypto import TYPE_DATA, PacketError, VpnCrypto, generate_secret, load_secret


class CryptoTests(unittest.TestCase):
    def test_client_server_round_trip(self):
        secret = load_secret(generate_secret())
        client = VpnCrypto("client", secret)
        server = VpnCrypto("server", secret)

        packet = client.seal(TYPE_DATA, b"hello")
        packet_type, payload = server.open(packet)

        self.assertEqual(packet_type, TYPE_DATA)
        self.assertEqual(payload, b"hello")

    def test_replay_is_rejected(self):
        secret = load_secret(generate_secret())
        client = VpnCrypto("client", secret)
        server = VpnCrypto("server", secret)

        packet = client.seal(TYPE_DATA, b"hello")
        server.open(packet)

        with self.assertRaises(PacketError):
            server.open(packet)

    def test_wrong_role_cannot_decrypt(self):
        secret = load_secret(generate_secret())
        client_a = VpnCrypto("client", secret)
        client_b = VpnCrypto("client", secret)

        packet = client_a.seal(TYPE_DATA, b"hello")

        with self.assertRaises(PacketError):
            client_b.open(packet)


if __name__ == "__main__":
    unittest.main()


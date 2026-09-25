"""The launcher: address detection, and what it tells you before you use it.

`server/serve.py` exists to answer two questions the plain uvicorn command
leaves open — what do I type into my phone, and what did I just expose.
Both answers are testable, so they are tested: address detection has a
loopback case and a no-network case, and the banner has to keep saying
that local mode has no login whenever it binds to the network.
"""

import unittest

from server import serve


class LanAddressTestCase(unittest.TestCase):
    def test_a_loopback_route_is_not_an_address_to_type_into_a_phone(self):
        """Probing 127.0.0.1 picks the loopback interface, which no other
        device can reach — reporting it would send someone to a dead URL."""
        self.assertIsNone(serve.lan_address(probe=("127.0.0.1", 80)))

    def test_no_route_is_reported_as_no_address_rather_than_raising(self):
        """An IPv6 target on an IPv4 socket fails the way an offline
        machine does: the launcher must degrade, not crash."""
        self.assertIsNone(serve.lan_address(probe=("::1", 80)))

    def test_the_real_probe_returns_a_usable_address_or_nothing(self):
        """Runs on whatever network the test machine has, including none,
        so it asserts the shape of the contract rather than a value."""
        address = serve.lan_address()
        if address is None:
            return
        self.assertFalse(address.startswith("127."))
        parts = address.split(".")
        self.assertEqual(len(parts), 4, address)
        for part in parts:
            self.assertTrue(part.isdigit(), address)
            self.assertLessEqual(int(part), 255, address)


class BannerTestCase(unittest.TestCase):
    def test_it_always_prints_the_address_for_this_computer(self):
        for local_only in (True, False):
            with self.subTest(local_only=local_only):
                self.assertIn("http://localhost:8000",
                              serve.banner(8000, local_only, "10.0.0.4"))

    def test_the_port_it_prints_is_the_port_it_was_given(self):
        text = serve.banner(9123, False, "10.0.0.4")
        self.assertIn("http://localhost:9123", text)
        self.assertIn("http://10.0.0.4:9123", text)

    def test_binding_to_the_network_says_the_app_has_no_login(self):
        """The warning is the point of the banner. If this test is ever
        deleted, delete the network binding with it."""
        text = serve.banner(8000, False, "192.168.1.20")
        self.assertIn("no", text.lower())
        self.assertIn("login", text)
        self.assertIn("Anyone on this network", text)

    def test_local_only_offers_no_phone_url_and_no_scare(self):
        text = serve.banner(8000, True, "192.168.1.20")
        self.assertNotIn("192.168.1.20", text)
        self.assertNotIn("On your phone", text)
        self.assertNotIn("login", text)
        self.assertIn("--local-only", text)

    def test_without_an_address_it_says_so_instead_of_inventing_one(self):
        text = serve.banner(8000, False, None)
        self.assertIn("No local network address found", text)
        self.assertNotIn("On your phone", text)
        self.assertIn("Anyone on this network", text)

    def test_it_is_honest_that_installing_to_a_home_screen_needs_https(self):
        for local_only in (True, False):
            with self.subTest(local_only=local_only):
                self.assertIn("HTTPS", serve.banner(8000, local_only, None))


class ArgumentTestCase(unittest.TestCase):
    """`main` itself is not called — it blocks inside uvicorn.run. Its
    parser is, because the flag names are the documented interface."""

    def test_the_defaults_serve_the_network_on_port_8000(self):
        args = serve.build_parser().parse_args([])
        self.assertEqual(args.port, 8000)
        self.assertFalse(args.local_only)
        self.assertFalse(args.reload)

    def test_the_documented_flags_are_accepted(self):
        args = serve.build_parser().parse_args(
            ["--port", "9000", "--local-only", "--reload"])
        self.assertEqual(args.port, 9000)
        self.assertTrue(args.local_only)
        self.assertTrue(args.reload)

    def test_a_non_numeric_port_is_refused_rather_than_guessed(self):
        with self.assertRaises(SystemExit):
            serve.build_parser().parse_args(["--port", "eight-thousand"])


if __name__ == "__main__":
    unittest.main()

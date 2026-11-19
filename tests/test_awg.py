import base64
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import ExitSpec
from reality_gateway.awg import AwgManager, render_awg_config


class AwgTests(unittest.TestCase):
    def test_failed_process_start_does_not_touch_inbound_wireguard(self):
        calls = []

        class FailedProcess:
            def poll(self):
                return 1

        manager = AwgManager(
            runner=lambda argv, **kwargs: calls.append(argv),
            popen=lambda argv: FailedProcess(),
        )
        with patch("reality_gateway.awg.Path.exists", return_value=False):
            with self.assertRaises(RuntimeError):
                manager.start(ExitSpec("first", "awg3", 10, {"address": "10.8.1.12/32"}))
        self.assertFalse(any("wg0" in argv for argv in calls))

    def test_render_uses_supplied_awg3_values_without_quick_routes(self):
        key = base64.b64encode(bytes(range(32))).decode()
        settings = {
            "endpoint": "198.51.100.10:51820", "private_key": key,
            "peer_public_key": key, "preshared_key": key,
            "header_protection_key": key, "jc": 5, "jmin": 10, "jmax": 50,
            "s1": 12, "s2": 12, "s3": 12, "s4": 12,
            "h1": 1, "h2": 2, "h3": 3, "h4": 4,
            "content_padding_addition": "10-100", "rekey_after_time": "100-120",
            "rekey_timeout": "3-7", "reject_after_time": "150-180",
            "keepalive_timeout": "5-15", "max_handshake_attempts": "15-20",
            "persistent_keepalive": "25-35", "random_trailers": True,
            "disable_cookies": True,
        }
        rendered = render_awg_config(ExitSpec("first", "awg3", 10, settings))
        self.assertIn("HeaderProtectionKey = " + key, rendered)
        self.assertIn("Endpoint = 198.51.100.10:51820", rendered)
        self.assertIn("RandomTrailers = on", rendered)
        self.assertNotIn("Address =", rendered)
        self.assertNotIn("DNS =", rendered)
        self.assertNotIn("PostUp", rendered)


if __name__ == "__main__":
    unittest.main()

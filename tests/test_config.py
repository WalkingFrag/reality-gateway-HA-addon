import json
import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import load_config


class ConfigTests(unittest.TestCase):
    def awg(self):
        key = lambda byte: base64.b64encode(bytes([byte]) * 32).decode()
        return {
            "id": "first", "priority": 10, "endpoint": "198.51.100.1:1234",
            "address": "10.8.1.12/32", "private_key": key(1),
            "peer_public_key": key(2), "preshared_key": key(3),
            "header_protection_key": key(4), "jc": 5, "jmin": 10,
            "jmax": 50, "s1": 12, "s2": 12, "s3": 12, "s4": 12,
            "h1": 1, "h2": 2, "h3": 3, "h4": 4,
            "content_padding_addition": "10-100", "rekey_after_time": "100-120",
            "rekey_timeout": "3-7", "reject_after_time": "150-180",
            "keepalive_timeout": "5-15", "max_handshake_attempts": "15-20",
            "persistent_keepalive": "25-35", "random_trailers": True,
            "disable_cookies": True,
        }

    def load(self, data):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "options.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_config(path)

    def test_existing_options_keep_vless_only_mode(self):
        config = self.load({"vless_server": "example.org"})
        self.assertTrue(config.legacy_mode)
        self.assertEqual([exit.id for exit in config.exits], ["vless"])

    def test_awg_servers_must_have_distinct_endpoints(self):
        entry = self.awg()
        second = {**entry, "id": "second", "priority": 20, "address": "10.8.1.13/32"}
        with self.assertRaisesRegex(ValueError, "endpoint"):
            self.load({"awg_exits": [entry, second], "probe_targets": [
                {"host": "one.example", "ip": "192.0.2.1", "path": "/", "expected_status": 200},
                {"host": "two.example", "ip": "192.0.2.2", "path": "/", "expected_status": 200},
            ]})

    def test_incomplete_awg_parameters_are_rejected(self):
        entry = self.awg()
        del entry["jc"]
        with self.assertRaisesRegex(ValueError, "jc"):
            self.load({"awg_exits": [entry], "probe_targets": [
                {"host": "one.example", "ip": "192.0.2.1", "path": "/", "expected_status": 200},
                {"host": "two.example", "ip": "192.0.2.2", "path": "/", "expected_status": 200},
            ]})


if __name__ == "__main__":
    unittest.main()

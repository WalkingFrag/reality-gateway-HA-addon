import json
import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import load_config
from reality_gateway.awg import render_awg_config
from reality_gateway.webui import add_awg, remove_awg, dashboard_status
from reality_gateway.status import config_fingerprint


def profile(endpoint="198.51.100.1:1234"):
    key = lambda byte: base64.b64encode(bytes([byte]) * 32).decode()
    entry = {"address": "10.8.1.12/32", "private_key": key(1),
             "header_protection_key": key(4), "peer_public_key": key(2),
             "preshared_key": key(3), "endpoint": endpoint,
             "jc": 5, "jmin": 10, "jmax": 50,
             "s1": 12, "s2": 12, "s3": 12, "s4": 12,
             "h1": 1, "h2": 2, "h3": 3, "h4": 4,
             "content_padding_addition": "10-100", "rekey_after_time": "100-120",
             "rekey_timeout": "3-7", "reject_after_time": "150-180",
             "keepalive_timeout": "5-15", "max_handshake_attempts": "15-20",
             "persistent_keepalive": "25-35"}
    interface = ["[Interface]", f"Address = {entry['address']}",
                 f"PrivateKey = {entry['private_key']}",
                 f"HeaderProtectionKey = {entry['header_protection_key']}"]
    for key in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4", "h1", "h2", "h3", "h4"):
        interface.append(f"{key.upper()} = {entry[key]}")
    for key in ("content_padding_addition", "rekey_after_time", "rekey_timeout",
                "reject_after_time", "keepalive_timeout", "max_handshake_attempts"):
        interface.append("".join(word.capitalize() for word in key.split("_")) + f" = {entry[key]}")
    interface += ["RandomTrailers = on", "DisableCookies = on"]
    peer = ["[Peer]", f"PublicKey = {entry['peer_public_key']}",
            f"PresharedKey = {entry['preshared_key']}",
            f"Endpoint = {entry['endpoint']}",
            f"PersistentKeepalive = {entry['persistent_keepalive']}"]
    return "\n".join(interface + [""] + peer)


class AwgUiTests(unittest.TestCase):
    def test_pasted_awg_appears_as_exit_and_can_be_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            options = Path(temp) / "options.json"
            vless = Path(temp) / "vless-exits.json"
            awg = Path(temp) / "awg-profiles.json"
            options.write_text("{}", encoding="utf-8")
            status_path = Path(temp) / "status.json"
            status_path.write_text(json.dumps({
                "updated_at": 100, "current": None, "exits": [],
                "config_fingerprint": config_fingerprint(vless),
                "awg_fingerprint": config_fingerprint(awg),
            }), encoding="utf-8")
            added = add_awg(awg, options, vless, "Москва", profile())
            config = load_config(options, vless, awg)
            self.assertEqual(config.exits[0].id, added["id"])
            self.assertEqual(config.exits[0].label, "Москва")
            self.assertEqual(config.exits[0].kind, "awg3")
            self.assertIn("Endpoint = 198.51.100.1:1234", render_awg_config(config.exits[0]))
            self.assertNotIn("PrivateKey", json.dumps(added))
            status = dashboard_status(status_path, vless, "", "", now=110, awg_path=awg)
            self.assertTrue(status["restart_required"])
            self.assertEqual(status["configured_awg"][0]["label"], "Москва")
            self.assertNotIn("PrivateKey", json.dumps(status))
            self.assertEqual(remove_awg(awg, added["id"]), [])

    def test_reject_duplicate_awg_endpoint_before_saving(self):
        with tempfile.TemporaryDirectory() as temp:
            options = Path(temp) / "options.json"
            vless = Path(temp) / "vless-exits.json"
            awg = Path(temp) / "awg-profiles.json"
            options.write_text("{}", encoding="utf-8")
            add_awg(awg, options, vless, "Первый", profile())
            with self.assertRaises(ValueError):
                add_awg(awg, options, vless, "Второй", profile())
            self.assertEqual(len(json.loads(awg.read_text())), 1)


if __name__ == "__main__":
    unittest.main()

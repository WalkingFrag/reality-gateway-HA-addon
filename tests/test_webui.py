import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.status import config_fingerprint
from reality_gateway.webui import add_vless, remove_vless, dashboard_status
from test_vless import LINK


class WebUiTests(unittest.TestCase):
    def test_add_remove_and_hide_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vless-exits.json"
            entry = add_vless(path, LINK)
            self.assertEqual(entry["label"], "Backup VLESS")
            self.assertNotIn("uuid", json.dumps(entry))
            self.assertEqual(len(json.loads(path.read_text())), 1)
            self.assertEqual(remove_vless(path, entry["id"]), [])

    def test_status_detects_pending_restart_and_missing_route(self):
        with tempfile.TemporaryDirectory() as temp:
            status_path = Path(temp) / "status.json"
            vless_path = Path(temp) / "vless-exits.json"
            vless_path.write_text("[]", encoding="utf-8")
            status_path.write_text(json.dumps({
                "updated_at": 100, "current": "vless", "config_fingerprint": config_fingerprint(vless_path),
                "exits": [{"id": "vless", "label": "Основной VLESS", "kind": "vless", "priority": 100, "health": "unknown"}],
            }), encoding="utf-8")
            state = dashboard_status(status_path, vless_path, "wg0\tkey\tpub\t51821\toff\n", "", now=110)
            self.assertFalse(state["route_ok"])
            self.assertFalse(state["restart_required"])
            add_vless(vless_path, LINK)
            state = dashboard_status(status_path, vless_path, "wg0\tkey\tpub\t51821\toff\n", "", now=110)
            self.assertTrue(state["restart_required"])
            self.assertNotIn("123e4567", json.dumps(state))


if __name__ == "__main__":
    unittest.main()

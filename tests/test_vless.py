import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import load_config, parse_vless_url
from reality_gateway.singbox_config import build_singbox_config


LINK = (
    "vless://123e4567-e89b-42d3-a456-426614174000@vpn.example.org:443"
    "?security=reality&encryption=none&flow=xtls-rprx-vision"
    "&pbk=QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M&sid=abcd1234"
    "&sni=www.example.org&fp=chrome#Backup%20VLESS"
)


class VlessTests(unittest.TestCase):
    def test_parse_link(self):
        parsed = parse_vless_url(LINK)
        self.assertEqual(parsed["label"], "Backup VLESS")
        self.assertEqual(parsed["server"], "vpn.example.org")
        self.assertEqual(parsed["port"], 443)
        self.assertEqual(parse_vless_url(LINK.replace("&flow=xtls-rprx-vision", ""))["flow"], "")

    def test_reject_non_reality_and_bad_key(self):
        with self.assertRaises(ValueError):
            parse_vless_url(LINK.replace("security=reality", "security=tls"))
        with self.assertRaises(ValueError):
            parse_vless_url(LINK.replace("pbk=QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M", "pbk=bad"))
        with self.assertRaises(ValueError):
            parse_vless_url(LINK.replace("security=reality", "type=grpc&security=reality"))

    def test_multiple_vless_exits_have_distinct_tuns_and_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            options = Path(temp) / "options.json"
            extras = Path(temp) / "vless-exits.json"
            options.write_text(json.dumps({
                "vless_server": "old.example.org", "vless_port": 444,
                "vless_uuid": "123e4567-e89b-42d3-a456-426614174000",
                "vless_flow": "xtls-rprx-vision",
                "vless_reality_public_key": "QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M",
                "vless_reality_short_id": "abcd1234", "vless_sni": "www.example.org",
            }), encoding="utf-8")
            extras.write_text(json.dumps([{"id": "v_a1", "url": LINK},
                                          {"id": "v_b2", "url": LINK.replace("vpn.example.org", "two.example.org")}]), encoding="utf-8")
            config = load_config(options, extras)
            self.assertEqual([item.id for item in config.exits], ["v_a1", "v_b2", "vless"])
            self.assertFalse(config.legacy_mode)
            singbox = build_singbox_config(json.loads(options.read_text()), config.exits)
            self.assertEqual([item["interface_name"] for item in singbox["inbounds"]],
                             ["tun-reality", "t_v_a1", "t_v_b2"])
            self.assertEqual(len(singbox["route"]["rules"]), 3)
            self.assertEqual(len({item["address"][0] for item in singbox["inbounds"]}), 3)


if __name__ == "__main__":
    unittest.main()

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import ExitSpec, GatewayConfig, ProbeTarget
from reality_gateway.controller import GatewayController
from reality_gateway.status import read_wireguard, write_status


class StatusTests(unittest.TestCase):
    def test_controller_selects_named_vless_interface(self):
        exits = (ExitSpec("v_a1", "vless", 101, label="Backup", vless_settings={"uuid": "secret"}),)
        class Network:
            selected = None
            def select(self, interface):
                self.selected = interface
        network = Network()
        controller = GatewayController(GatewayConfig(exits, (ProbeTarget("x", "192.0.2.1", "/", 200),), False),
                                       network, prober=lambda *_: True)
        for i in range(3):
            controller.step(i * 15)
        self.assertEqual(network.selected, "t_v_a1")

    def test_two_vless_exits_fail_over_independently(self):
        exits = (ExitSpec("v_a1", "vless", 101), ExitSpec("v_b2", "vless", 102),
                 ExitSpec("vless", "vless", 200))
        class Network:
            selected = None
            def select(self, interface):
                self.selected = interface
        network = Network()
        reachable = {"v_a1": True, "v_b2": True, "vless": True}
        controller = GatewayController(GatewayConfig(exits, (ProbeTarget("x", "192.0.2.1", "/", 200),), False),
                                       network, prober=lambda item, *_: reachable[item.id])
        for i in range(3): controller.step(i * 15)
        self.assertEqual(network.selected, "t_v_a1")
        reachable["v_a1"] = False
        for i in range(3, 6): controller.step(i * 15)
        self.assertEqual(network.selected, "t_v_b2")

    def test_selected_route_is_repaired_after_interface_recreation(self):
        exits = (ExitSpec("v_a1", "vless", 101),)
        class Network:
            selected = None
            def select(self, interface):
                self.selected = interface
        network = Network()
        interface_up = [True]
        controller = GatewayController(GatewayConfig(exits, (ProbeTarget("x", "192.0.2.1", "/", 200),), False),
                                       network, prober=lambda *_: True, ready=lambda _: interface_up[0])
        for i in range(3): controller.step(i * 15)
        self.assertEqual(network.selected, "t_v_a1")
        network.selected = None  # kernel route disappeared with the TUN
        controller.step(45)
        self.assertEqual(network.selected, "t_v_a1")
        interface_up[0] = False
        controller.step(60)
        self.assertIsNone(network.selected)
        interface_up[0] = True
        controller.step(75)
        self.assertEqual(network.selected, "t_v_a1")

    def test_status_contains_no_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "status.json"
            exits = (ExitSpec("v_a1", "vless", 101, label="Backup", vless_settings={"uuid": "secret"}),)
            write_status(path, exits, "v_a1", {"v_a1": True}, 123)
            value = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", value)
            self.assertEqual(json.loads(value)["current"], "v_a1")

    def test_wireguard_handshake_and_traffic(self):
        dump = "wg0\tkey\tpub\t51821\toff\npeer\tpsk\t(none)\t10.20.30.2/32\t1700\t100\t250\t25\n"
        status = read_wireguard(dump, now=1760)
        self.assertEqual(status["handshake_age_seconds"], 60)
        self.assertEqual(status["received_bytes"], 100)
        self.assertEqual(status["sent_bytes"], 250)
        self.assertEqual(status["state"], "recent")
        self.assertEqual(read_wireguard(dump, now=2000)["state"], "stale")


if __name__ == "__main__":
    unittest.main()

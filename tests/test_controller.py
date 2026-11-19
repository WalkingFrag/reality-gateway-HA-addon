import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import ExitSpec
from reality_gateway.controller import GatewayState, GatewayController, choose_exit
from reality_gateway.config import GatewayConfig, ProbeTarget


class ControllerTests(unittest.TestCase):
    def test_manual_priority_bypasses_hold_and_keeps_fallback(self):
        exits = (ExitSpec("awg1", "awg3", 10), ExitSpec("vless", "vless", 100))
        state = GatewayState(exits, current="awg1", switched_at=100)
        state.healthy = {"awg1": True, "vless": True}
        order = ("vless", "awg1")
        self.assertEqual(choose_exit(state, 101, order, manual=True), "vless")
        state.healthy["vless"] = False
        self.assertEqual(choose_exit(state, 101, order, manual=True), "awg1")

    def test_three_successful_rounds_select_awg(self):
        exits = (ExitSpec("awg1", "awg3", 10), ExitSpec("vless", "vless", 100))
        target = ProbeTarget("one.example", "192.0.2.1", "/", 200)

        class Network:
            def __init__(self):
                self.selections = []

            def select(self, interface):
                self.selections.append(interface)

        network = Network()
        controller = GatewayController(
            GatewayConfig(exits, (target, target), False), network,
            prober=lambda exit, target, mark, timeout: exit.id == "awg1",
        )
        controller.step(0)
        controller.step(15)
        controller.step(30)
        self.assertEqual(network.selections[-1], "a_awg1")

    def test_failed_current_exit_switches_to_healthy_backup(self):
        exits = (ExitSpec("awg1", "awg3", 10), ExitSpec("vless", "vless", 100))
        state = GatewayState(exits)
        state.current = "awg1"
        state.healthy = {"awg1": False, "vless": True}
        self.assertEqual(choose_exit(state, 10), "vless")

    def test_failback_waits_two_minutes(self):
        exits = (ExitSpec("awg1", "awg3", 10), ExitSpec("vless", "vless", 100))
        state = GatewayState(exits)
        state.current = "vless"
        state.switched_at = 100
        state.healthy = {"awg1": True, "vless": True}
        self.assertEqual(choose_exit(state, 150), "vless")
        self.assertEqual(choose_exit(state, 221), "awg1")

    def test_all_down_blocks(self):
        exits = (ExitSpec("awg1", "awg3", 10), ExitSpec("vless", "vless", 100))
        state = GatewayState(exits)
        state.healthy = {"awg1": False, "vless": False}
        self.assertIsNone(choose_exit(state, 100))


if __name__ == "__main__":
    unittest.main()

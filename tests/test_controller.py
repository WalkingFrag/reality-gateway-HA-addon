import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import ExitSpec
from reality_gateway.controller import GatewayState, choose_exit


class ControllerTests(unittest.TestCase):
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

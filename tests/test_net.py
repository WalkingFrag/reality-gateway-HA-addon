import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.net import NetworkManager


class NetworkTests(unittest.TestCase):
    def test_probe_route_has_its_own_blackhole_and_mark(self):
        commands = []
        network = NetworkManager(lambda args, **kwargs: commands.append(args))
        network.configure_probe_route("a_first", 101)
        self.assertIn(["ip", "route", "replace", "blackhole", "default", "table", "101", "metric", "32767"], commands)
        self.assertIn(["ip", "route", "replace", "default", "dev", "a_first", "table", "101", "metric", "100"], commands)
        self.assertIn(["ip", "rule", "add", "fwmark", "101", "table", "101"], commands)

    def test_reconcile_does_not_duplicate_existing_policy_rule(self):
        commands = []
        calls = []

        def runner(args, **kwargs):
            commands.append(args)
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="100: from all fwmark 0x64 lookup 100")

        NetworkManager(runner).reconcile(())
        self.assertFalse(any(cmd[:3] == ["ip", "rule", "add"] for cmd in commands))
        self.assertTrue(any(args == ["ip", "rule", "show"] and kwargs.get("capture_output") for args, kwargs in calls))

    def test_blackhole_precedes_policy_rule_and_survives_all_down(self):
        commands = []
        network = NetworkManager(lambda args, **kwargs: commands.append(args))
        network.reconcile(())
        network.select("tun-reality")
        network.select(None)
        blackhole = [i for i, cmd in enumerate(commands) if cmd[:5] == ["ip", "route", "replace", "blackhole", "default"]]
        policy = [i for i, cmd in enumerate(commands) if cmd[:3] == ["ip", "rule", "add"]]
        self.assertTrue(blackhole)
        self.assertTrue(policy)
        self.assertLess(blackhole[0], policy[0])
        self.assertIn(["ip", "route", "del", "blackhole", "default", "table", "100", "metric", "0"], commands)
        self.assertIn(["ip", "route", "replace", "blackhole", "default", "table", "100", "metric", "32767"], commands)
        self.assertTrue(any(cmd[:4] == ["ip", "route", "del", "default"] for cmd in commands))


if __name__ == "__main__":
    unittest.main()

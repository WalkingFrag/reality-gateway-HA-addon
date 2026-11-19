"""Host policy routing for traffic received on wg0."""

import subprocess


class NetworkManager:
    def __init__(self, runner=subprocess.run):
        self.runner = runner
        self.selected = None

    def _run(self, args, check=True, **kwargs):
        return self.runner(args, check=check, **kwargs)

    def _rule(self, table, chain, match, target):
        base = ["iptables", "-t", table, "-C", chain, *match, *target]
        result = self._run(base, check=False)
        if result is None or result.returncode != 0:
            self._run(["iptables", "-t", table, "-A", chain, *match, *target])

    def reconcile(self, exits):
        self._run(["ip", "route", "replace", "blackhole", "default", "table", "100", "metric", "32767"])
        self._rule("mangle", "PREROUTING", ["-i", "wg0"], ["-j", "MARK", "--set-mark", "100"])
        result = self._run(["ip", "rule", "show"], check=False, capture_output=True, text=True)
        text = getattr(result, "stdout", "") or ""
        if "fwmark 0x64 lookup 100" not in text:
            self._run(["ip", "rule", "add", "fwmark", "100", "table", "100"])
        self._run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
        for exit in exits:
            if exit.kind == "awg3":
                name = "a_" + exit.id
                self._rule("nat", "POSTROUTING", ["-o", name], ["-j", "MASQUERADE"])
                self._rule("filter", "DOCKER-USER", ["-i", "wg0", "-o", name], ["-j", "ACCEPT"])
                self._rule("filter", "DOCKER-USER", ["-i", name, "-o", "wg0"], ["-j", "ACCEPT"])
                self._rule("mangle", "FORWARD", ["-o", name, "-p", "tcp", "--tcp-flags", "SYN,RST", "SYN"], ["-j", "TCPMSS", "--clamp-mss-to-pmtu"])

    def select(self, interface):
        if interface is None:
            self._run(["ip", "route", "del", "default", "table", "100", "metric", "100"], check=False)
        else:
            self._run(["ip", "route", "replace", "default", "dev", interface, "table", "100", "metric", "100"])
        self.selected = interface

    def cleanup(self):
        self.select(None)
        self._run(["ip", "link", "set", "wg0", "down"], check=False)
        self._run(["ip", "rule", "del", "fwmark", "100", "table", "100"], check=False)

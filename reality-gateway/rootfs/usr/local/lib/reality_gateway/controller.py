"""Health state and priority selection for AWG3/VLESS egress."""

from dataclasses import dataclass, field
import logging
from pathlib import Path
import signal
import subprocess
import time

from .awg import AwgManager
from .config import ExitSpec, GatewayConfig, load_config
from .net import NetworkManager
from .probe import probe


@dataclass
class GatewayState:
    exits: tuple[ExitSpec, ...]
    current: str | None = None
    switched_at: float = 0.0
    healthy: dict[str, bool] = field(default_factory=dict)
    successes: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)

    def record(self, exit_id: str, success: bool) -> None:
        if success:
            self.successes[exit_id] = self.successes.get(exit_id, 0) + 1
            self.failures[exit_id] = 0
            if self.successes[exit_id] >= 3:
                self.healthy[exit_id] = True
        else:
            self.failures[exit_id] = self.failures.get(exit_id, 0) + 1
            self.successes[exit_id] = 0
            if self.failures[exit_id] >= 3:
                self.healthy[exit_id] = False


def choose_exit(state: GatewayState, now: float) -> str | None:
    healthy = [exit for exit in state.exits if state.healthy.get(exit.id, False)]
    if not healthy:
        return None
    preferred = min(healthy, key=lambda exit: exit.priority).id
    if state.current and state.healthy.get(state.current, False):
        if state.current != preferred and now - state.switched_at < 120:
            return state.current
    return preferred


class GatewayController:
    def __init__(self, config: GatewayConfig, network: NetworkManager,
                 prober=probe, ready=None):
        self.config = config
        self.network = network
        self.prober = prober
        self.ready = ready or (lambda exit: True)
        self.state = GatewayState(config.exits)
        self.marks = {exit.id: 101 + index for index, exit in enumerate(config.exits)}

    def step(self, now: float) -> None:
        for exit in self.config.exits:
            success = self.ready(exit) and any(
                self.prober(exit, target, self.marks[exit.id], 5)
                for target in self.config.probes
            )
            self.state.record(exit.id, success)
        selected = choose_exit(self.state, now)
        if selected != self.state.current:
            interface = None if selected is None else (
                "tun-reality" if selected == "vless" else "a_" + selected
            )
            self.network.select(interface)
            logging.info("Selected egress: %s", selected or "none")
            self.state.current = selected
            self.state.switched_at = now


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    config = load_config(Path("/data/options.json"))
    network = NetworkManager()
    awg = AwgManager()
    network.reconcile(config.exits)
    network.select(None)
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if config.legacy_mode:
            while running:
                if Path("/sys/class/net/tun-reality").exists():
                    network.select("tun-reality")
                    break
                time.sleep(2)
            while running:
                time.sleep(15)
            return
        controller = GatewayController(
            config, network,
            ready=lambda exit: (Path("/sys/class/net/tun-reality").exists()
                                if exit.kind == "vless" else awg.is_running(exit.id)),
        )
        while running:
            for exit in config.exits:
                if exit.kind == "awg3" and not awg.is_running(exit.id):
                    try:
                        interface = awg.start(exit)
                        network.configure_probe_route(interface, controller.marks[exit.id])
                    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
                        logging.warning("AWG exit %s unavailable: %s", exit.id, type(exc).__name__)
                elif exit.kind == "vless" and Path("/sys/class/net/tun-reality").exists():
                    network.configure_probe_route("tun-reality", controller.marks[exit.id])
            controller.step(time.monotonic())
            time.sleep(15)
    finally:
        network.select(None)
        for exit in config.exits:
            if exit.kind == "awg3":
                awg.stop(exit.id)
        network.cleanup()


if __name__ == "__main__":
    main()

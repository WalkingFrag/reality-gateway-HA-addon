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
from .singbox_config import vless_interface
from .status import config_fingerprint, write_status

STATUS_PATH = Path("/run/reality-gateway/status.json")
VLESS_PATH = Path("/data/vless-exits.json")
AWG_PATH = Path("/data/awg-profiles.json")


def publish_status(exits, current, healthy, fingerprint, awg_fingerprint):
    write_status(STATUS_PATH, exits, current, healthy,
                 fingerprint=fingerprint, awg_fingerprint=awg_fingerprint)


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
                 prober=probe, ready=None, fingerprint="", awg_fingerprint="",
                 status_path=None):
        self.config = config
        self.network = network
        self.prober = prober
        self.ready = ready or (lambda exit: True)
        self.state = GatewayState(config.exits)
        self.marks = {exit.id: 101 + index for index, exit in enumerate(config.exits)}
        self.fingerprint = fingerprint
        self.awg_fingerprint = awg_fingerprint
        self.status_path = status_path

    def step(self, now: float) -> None:
        for exit in self.config.exits:
            success = self.ready(exit) and any(
                self.prober(exit, target, self.marks[exit.id], 5)
                for target in self.config.probes
            )
            self.state.record(exit.id, success)
        selected = choose_exit(self.state, now)
        selected_exit = next((item for item in self.config.exits if item.id == selected), None)
        interface = None if selected_exit is None else (
            vless_interface(selected) if selected_exit.kind == "vless" else "a_" + selected)
        if selected != self.state.current:
            self.network.select(interface if selected_exit is None or self.ready(selected_exit) else None)
            logging.info("Selected egress: %s", selected or "none")
            self.state.current = selected
            self.state.switched_at = now
        elif selected_exit is not None:
            # A TUN restart removes kernel routes even when the health threshold
            # has not switched candidates. Reconcile the desired route every round.
            self.network.select(interface if self.ready(selected_exit) else None)
        if self.status_path is not None:
            write_status(self.status_path, self.config.exits, self.state.current,
                         self.state.healthy, fingerprint=self.fingerprint,
                         awg_fingerprint=self.awg_fingerprint)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    try:
        config = load_config(Path("/data/options.json"))
    except (ValueError, TypeError, KeyError, AttributeError):
        logging.error("AWG options invalid; continuing with existing VLESS exit")
        config = GatewayConfig((ExitSpec("vless", "vless", 100),), (), True)
    network = NetworkManager()
    awg = AwgManager()
    fingerprint = config_fingerprint(VLESS_PATH)
    awg_fingerprint = config_fingerprint(AWG_PATH)
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
                publish_status(config.exits, None, {}, fingerprint, awg_fingerprint)
                time.sleep(2)
            while running:
                publish_status(config.exits, "vless", {}, fingerprint, awg_fingerprint)
                time.sleep(15)
            return
        controller = GatewayController(
            config, network,
            fingerprint=fingerprint,
            awg_fingerprint=awg_fingerprint,
            status_path=STATUS_PATH,
            ready=lambda exit: (Path("/sys/class/net/" + vless_interface(exit.id)).exists()
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
                elif exit.kind == "vless" and Path("/sys/class/net/" + vless_interface(exit.id)).exists():
                    network.configure_probe_route(vless_interface(exit.id), controller.marks[exit.id])
            controller.step(time.monotonic())
            time.sleep(15)
    finally:
        network.select(None)
        publish_status(config.exits, None, {}, fingerprint, awg_fingerprint)
        for exit in config.exits:
            if exit.kind == "awg3":
                awg.stop(exit.id)
        network.cleanup()


if __name__ == "__main__":
    main()

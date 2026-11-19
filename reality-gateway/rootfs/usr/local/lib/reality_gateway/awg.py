"""AWG3 userspace interface setup; never install a host default route."""

import os
from pathlib import Path
import subprocess
import tempfile
import time

from .config import ExitSpec


_INTERFACE_FIELDS = {
    "private_key": "PrivateKey",
    "jc": "Jc", "jmin": "Jmin", "jmax": "Jmax",
    "s1": "S1", "s2": "S2", "s3": "S3", "s4": "S4",
    "h1": "H1", "h2": "H2", "h3": "H3", "h4": "H4",
    "header_protection_key": "HeaderProtectionKey",
    "content_padding_addition": "ContentPaddingAddition",
    "rekey_after_time": "RekeyAfterTime",
    "rekey_timeout": "RekeyTimeout",
    "reject_after_time": "RejectAfterTime",
    "keepalive_timeout": "KeepaliveTimeout",
    "max_handshake_attempts": "MaxHandshakeAttempts",
    "random_trailers": "RandomTrailers",
    "disable_cookies": "DisableCookies",
}


def render_awg_config(exit: ExitSpec) -> str:
    if exit.kind != "awg3" or not exit.awg_settings:
        raise ValueError("AWG3 exit required")
    settings = exit.awg_settings
    lines = ["[Interface]"]
    for source, target in _INTERFACE_FIELDS.items():
        value = settings[source]
        if isinstance(value, bool):
            value = "on" if value else "off"
        lines.append(f"{target} = {value}")
    lines.extend(("", "[Peer]"))
    for source, target in (
        ("peer_public_key", "PublicKey"),
        ("preshared_key", "PresharedKey"),
        ("endpoint", "Endpoint"),
        ("persistent_keepalive", "PersistentKeepalive"),
    ):
        lines.append(f"{target} = {settings[source]}")
    lines.append("AllowedIPs = 0.0.0.0/0")
    return "\n".join(lines) + "\n"


class AwgManager:
    def __init__(self, runner=subprocess.run, popen=subprocess.Popen):
        self.runner = runner
        self.popen = popen
        self.processes = {}

    def start(self, exit: ExitSpec) -> str:
        name = "a_" + exit.id
        if len(name) > 15:
            raise ValueError("AWG interface name too long")
        if self.is_running(exit.id):
            return name
        process = self.popen(["amneziawg-go", "-f", name])
        self.processes[exit.id] = process
        try:
            for _ in range(50):
                if Path(f"/var/run/amneziawg/{name}.sock").exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"AWG process exited for {exit.id}")
                time.sleep(0.1)
            else:
                raise TimeoutError(f"AWG control socket missing for {exit.id}")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as temp:
                os.fchmod(temp.fileno(), 0o600)
                temp.write(render_awg_config(exit))
                path = temp.name
            try:
                self.runner(["awg", "setconf", name, path], check=True)
            finally:
                os.unlink(path)
            self.runner(["ip", "addr", "replace", exit.awg_settings["address"], "dev", name], check=True)
            self.runner(["ip", "link", "set", name, "mtu", "1280", "up"], check=True)
            return name
        except Exception:
            self.stop(exit.id)
            raise

    def is_running(self, exit_id: str) -> bool:
        process = self.processes.get(exit_id)
        return process is not None and process.poll() is None

    def stop(self, exit_id: str) -> None:
        process = self.processes.pop(exit_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self.runner(["ip", "link", "del", "a_" + exit_id], check=False)

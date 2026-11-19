"""Validate Supervisor options before touching host networking."""

from dataclasses import dataclass
import base64
import binascii
from ipaddress import ip_address, ip_interface
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class ExitSpec:
    id: str
    kind: str
    priority: int
    awg_settings: dict | None = None


@dataclass(frozen=True)
class ProbeTarget:
    host: str
    ip: str
    path: str
    expected_status: int


@dataclass(frozen=True)
class GatewayConfig:
    exits: tuple[ExitSpec, ...]
    probes: tuple[ProbeTarget, ...]
    legacy_mode: bool


def load_config(options_path: Path) -> GatewayConfig:
    options = json.loads(options_path.read_text(encoding="utf-8"))
    raw_exits = options.get("awg_exits") or []
    if not isinstance(raw_exits, list):
        raise ValueError("awg_exits must be a list")
    if not raw_exits:
        return GatewayConfig((ExitSpec("vless", "vless", 100),), (), True)
    exits = []
    ids, priorities, addresses, endpoints = set(), set(), set(), set()
    for item in raw_exits:
        name = item.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,14}", name):
            raise ValueError("invalid AWG exit id")
        priority = item.get("priority")
        if not isinstance(priority, int) or priority < 1 or priority > 99:
            raise ValueError("invalid AWG priority")
        endpoint = item.get("endpoint", "")
        host, sep, port = endpoint.rpartition(":")
        if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("invalid AWG endpoint")
        try:
            address = str(ip_interface(item.get("address", "")))
        except ValueError as exc:
            raise ValueError("invalid AWG address") from exc
        if name in ids or priority in priorities or address in addresses or endpoint in endpoints:
            raise ValueError("duplicate id, priority, address, or endpoint")
        for field in ("private_key", "peer_public_key", "preshared_key", "header_protection_key"):
            value = item.get(field, "")
            try:
                decoded = base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError, TypeError) as exc:
                raise ValueError(f"invalid {field}") from exc
            if len(decoded) != 32:
                raise ValueError(f"invalid {field}")
        for field in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4", "h1", "h2", "h3", "h4"):
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"invalid {field}")
        for field in ("content_padding_addition", "rekey_after_time", "rekey_timeout", "reject_after_time", "keepalive_timeout", "max_handshake_attempts", "persistent_keepalive"):
            if not re.fullmatch(r"\d+(?:-\d+)?", str(item.get(field, ""))):
                raise ValueError(f"invalid {field}")
        for field in ("random_trailers", "disable_cookies"):
            if not isinstance(item.get(field), bool):
                raise ValueError(f"invalid {field}")
        if min(item[f"s{i}"] for i in range(1, 5)) < 12:
            raise ValueError("AWG3 header protection requires S1-S4 >= 12")
        ids.add(name); priorities.add(priority); addresses.add(address); endpoints.add(endpoint)
        exits.append(ExitSpec(name, "awg3", priority, item))
    raw_probes = options.get("probe_targets") or []
    if len(raw_probes) < 2:
        raise ValueError("at least two probe targets required")
    probes = []
    for item in raw_probes:
        ip = str(ip_address(item["ip"]))
        host = item["host"]
        path = item["path"]
        status = item["expected_status"]
        if not host or not path.startswith("/") or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError("invalid probe target")
        probes.append(ProbeTarget(host, ip, path, status))
    exits.append(ExitSpec("vless", "vless", 100))
    return GatewayConfig(tuple(sorted(exits, key=lambda item: item.priority)), tuple(probes), False)

"""Validate Supervisor options before touching host networking."""

from dataclasses import dataclass
import base64
import binascii
import configparser
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


def parse_awg_text(text: str, index: int) -> dict:
    """Convert a pasted Amnezia [Interface]/[Peer] profile into options."""
    if not isinstance(text, str) or len(text) > 16384:
        raise ValueError("invalid AWG profile text")
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text)
        interface, peer = parser["Interface"], parser["Peer"]
        fields = {
            "address": interface["Address"],
            "private_key": interface["PrivateKey"],
            "peer_public_key": peer["PublicKey"],
            "preshared_key": peer["PresharedKey"],
            "endpoint": peer["Endpoint"],
            "header_protection_key": interface["HeaderProtectionKey"],
        }
        for field in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4", "h1", "h2", "h3", "h4"):
            fields[field] = interface.getint(field)
        for field, source in (
            ("content_padding_addition", "ContentPaddingAddition"),
            ("rekey_after_time", "RekeyAfterTime"),
            ("rekey_timeout", "RekeyTimeout"),
            ("reject_after_time", "RejectAfterTime"),
            ("keepalive_timeout", "KeepaliveTimeout"),
            ("max_handshake_attempts", "MaxHandshakeAttempts"),
        ):
            fields[field] = interface[source]
        for field, source in (("random_trailers", "RandomTrailers"),
                              ("disable_cookies", "DisableCookies")):
            value = interface[source].lower()
            if value not in ("on", "off"):
                raise ValueError("invalid AWG boolean")
            fields[field] = value == "on"
        fields["persistent_keepalive"] = peer.get("PersistentKeepalive", "25")
    except (configparser.Error, KeyError, ValueError) as exc:
        raise ValueError(f"invalid AWG profile #{index}: expected complete [Interface] and [Peer] blocks") from exc
    fields.update(id=f"exit{index}", priority=index)
    return fields


def load_config(options_path: Path) -> GatewayConfig:
    options = json.loads(options_path.read_text(encoding="utf-8"))
    raw_exits = options.get("awg_exits") or []
    if not isinstance(raw_exits, list):
        raise ValueError("awg_exits must be a list")
    raw_profiles = options.get("awg_configs") or []
    if not isinstance(raw_profiles, list):
        raise ValueError("awg_configs must be a list")
    if raw_exits and raw_profiles:
        raise ValueError("use either awg_configs or awg_exits")
    if raw_profiles:
        raw_exits = [parse_awg_text(profile, index) for index, profile in enumerate(raw_profiles, 1)]
    if not raw_exits:
        return GatewayConfig((ExitSpec("vless", "vless", 100),), (), True)
    exits = []
    ids, priorities, addresses, endpoints = set(), set(), set(), set()
    for item in raw_exits:
        name = item.get("id", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,12}", name) or name == "vless":
            raise ValueError("invalid AWG exit id")
        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 1 or priority > 99:
            raise ValueError("invalid AWG priority")
        endpoint = item.get("endpoint", "")
        host, sep, port = endpoint.rpartition(":")
        if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("invalid AWG endpoint")
        try:
            if ip_address(host).version != 4:
                raise ValueError("IPv4 endpoint required")
        except ValueError as exc:
            raise ValueError("invalid IPv4 AWG endpoint") from exc
        try:
            address = str(ip_interface(item.get("address", "")))
        except ValueError as exc:
            raise ValueError("invalid AWG address") from exc
        if ip_interface(address).version != 4:
            raise ValueError("IPv4 AWG address required")
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
    raw_probes = options.get("probe_targets") or [
        {"host": "one.one.one.one", "ip": "1.1.1.1", "path": "/cdn-cgi/trace", "expected_status": 200},
        {"host": "dns.google", "ip": "8.8.8.8", "path": "/resolve?name=example.com&type=A", "expected_status": 200},
    ]
    if len(raw_probes) < 2:
        raise ValueError("at least two probe targets required")
    probes = []
    for item in raw_probes:
        ip = str(ip_address(item["ip"]))
        if ip_address(ip).version != 4:
            raise ValueError("IPv4 probe target required")
        host = item["host"]
        path = item["path"]
        status = item["expected_status"]
        if not host or not path.startswith("/") or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError("invalid probe target")
        probes.append(ProbeTarget(host, ip, path, status))
    exits.append(ExitSpec("vless", "vless", 100))
    return GatewayConfig(tuple(sorted(exits, key=lambda item: item.priority)), tuple(probes), False)

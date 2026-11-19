"""Validate Supervisor options before touching host networking."""

from dataclasses import dataclass
import base64
import binascii
import configparser
from ipaddress import ip_address, ip_interface
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID


@dataclass(frozen=True)
class ExitSpec:
    id: str
    kind: str
    priority: int
    awg_settings: dict | None = None
    label: str | None = None
    vless_settings: dict | None = None


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


_AWG_PROFILE_KEYS = (
    "Address", "DNS", "MTU", "PrivateKey", "HeaderProtectionKey",
    "Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4",
    "H1", "H2", "H3", "H4", "ContentPaddingAddition",
    "RekeyAfterTime", "RekeyTimeout", "RejectAfterTime",
    "KeepaliveTimeout", "MaxHandshakeAttempts", "RandomTrailers",
    "DisableCookies", "PublicKey", "PresharedKey", "AllowedIPs",
    "Endpoint", "PersistentKeepalive",
)
_FLAT_AWG_BOUNDARY = re.compile(
    r"\s+(?=(?:\[(?:Interface|Peer)\]|(?:" + "|".join(_AWG_PROFILE_KEYS) + r")\s*=))",
    re.IGNORECASE,
)


def parse_awg_text(text: str, index: int) -> dict:
    """Convert a pasted Amnezia [Interface]/[Peer] profile into options."""
    if not isinstance(text, str) or len(text) > 16384:
        raise ValueError("invalid AWG profile text")
    # Supervisor can collapse a YAML block scalar to one line. Recover only
    # known section/field boundaries; never split key material or free text.
    if "\n" not in text and "\r" not in text:
        text = _FLAT_AWG_BOUNDARY.sub("\n", text)
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


def parse_vless_url(url: str) -> dict:
    """Parse a VLESS+Reality share link without ever exposing its credentials."""
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("invalid VLESS link")
    try:
        link = urlsplit(url)
        if link.scheme != "vless" or not link.hostname or not link.port or not link.username:
            raise ValueError("invalid VLESS link")
        UUID(link.username)
        if not 1 <= link.port <= 65535:
            raise ValueError("invalid VLESS port")
        host = link.hostname
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) or ".." in host:
            raise ValueError("invalid VLESS host")
        query = parse_qs(link.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            raise ValueError("duplicate VLESS parameter")
        param = lambda key, default="": query.get(key, [default])[0]
        if (param("security") != "reality" or param("encryption", "none") != "none"
                or param("type", "tcp") != "tcp"):
            raise ValueError("VLESS+Reality link required")
        key = param("pbk")
        decoded = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
        if len(decoded) != 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError("invalid Reality public key")
        short_id = param("sid")
        if not re.fullmatch(r"[0-9a-fA-F]{0,32}", short_id) or len(short_id) % 2:
            raise ValueError("invalid Reality short ID")
        sni = param("sni")
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", sni) or ".." in sni:
            raise ValueError("invalid Reality SNI")
        flow = param("flow")
        fingerprint = param("fp", "chrome")
        if flow not in ("xtls-rprx-vision", "") or fingerprint not in ("chrome", "firefox", "safari", "edge"):
            raise ValueError("unsupported VLESS flow or fingerprint")
        label = unquote(link.fragment).strip() or host
        if len(label) > 48 or any(ord(char) < 32 for char in label):
            raise ValueError("invalid VLESS name")
        return {"label": label, "server": host, "port": link.port,
                "uuid": str(UUID(link.username)), "flow": flow,
                "public_key": key, "short_id": short_id, "sni": sni,
                "fingerprint": fingerprint}
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("invalid VLESS+Reality link") from exc


def load_config(options_path: Path, vless_path: Path = Path("/data/vless-exits.json"),
                awg_path: Path = Path("/data/awg-profiles.json"),
                managed_awg: list | None = None) -> GatewayConfig:
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
    if managed_awg is None:
        managed_awg = json.loads(awg_path.read_text(encoding="utf-8")) if awg_path.exists() else []
    if not isinstance(managed_awg, list) or len(managed_awg) > 20:
        raise ValueError("invalid managed AWG list")
    next_priority = max((item.get("priority", 0) for item in raw_exits), default=0)
    for index, item in enumerate(managed_awg, 1):
        if not isinstance(item, dict) or not re.fullmatch(r"w_[a-z0-9]{1,10}", str(item.get("id", ""))):
            raise ValueError("invalid managed AWG ID")
        name = item.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48 or any(ord(char) < 32 for char in name):
            raise ValueError("invalid managed AWG name")
        if next_priority + index > 99:
            raise ValueError("too many AWG exits")
        parsed = parse_awg_text(item.get("profile"), index)
        parsed.update(id=item["id"], priority=next_priority + index, label=name.strip())
        raw_exits.append(parsed)
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
        if name in ids:
            raise ValueError("duplicate AWG ID")
        if priority in priorities:
            raise ValueError("duplicate AWG priority")
        if address in addresses:
            raise ValueError("duplicate AWG address")
        if endpoint in endpoints:
            raise ValueError("duplicate AWG endpoint")
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
        exits.append(ExitSpec(name, "awg3", priority, item, label=item.get("label")))
    if vless_path.exists():
        extra_vless = json.loads(vless_path.read_text(encoding="utf-8"))
        if not isinstance(extra_vless, list) or len(extra_vless) > 20:
            raise ValueError("invalid VLESS exit list")
    else:
        extra_vless = []
    vless_ids = set()
    for index, item in enumerate(extra_vless, 1):
        if not isinstance(item, dict) or not re.fullmatch(r"v_[a-z0-9]{1,10}", str(item.get("id", ""))):
            raise ValueError("invalid VLESS exit ID")
        if item["id"] in vless_ids or item["id"] in ids:
            raise ValueError("duplicate exit ID")
        vless_ids.add(item["id"])
        settings = parse_vless_url(item.get("url"))
        exits.append(ExitSpec(item["id"], "vless", 100 + index, label=settings["label"],
                              vless_settings=settings))
    legacy_mode = not raw_exits and not extra_vless
    if legacy_mode:
        return GatewayConfig((ExitSpec("vless", "vless", 100, label="Основной VLESS"),), (), True)
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
    exits.append(ExitSpec("vless", "vless", 200 if extra_vless else 100,
                          label="Основной VLESS"))
    return GatewayConfig(tuple(sorted(exits, key=lambda item: item.priority)), tuple(probes), False)

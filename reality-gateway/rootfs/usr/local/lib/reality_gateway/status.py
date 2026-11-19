"""Sanitized runtime status shared with the ingress panel."""

import json
import hashlib
import os
from pathlib import Path
import time


def config_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.exists() else b"[]").hexdigest()


def write_status(path: Path, exits: tuple, current: str | None,
                 healthy: dict[str, bool], now: float | None = None,
                 fingerprint: str = "", awg_fingerprint: str = "") -> None:
    payload = {
        "updated_at": time.time() if now is None else now,
        "current": current,
        "config_fingerprint": fingerprint,
        "awg_fingerprint": awg_fingerprint,
        "exits": [{"id": item.id, "label": item.label or item.id,
                   "kind": item.kind, "priority": item.priority,
                   "health": ("healthy" if healthy[item.id] else "unhealthy")
                   if item.id in healthy else "unknown"} for item in exits],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_wireguard(dump: str, now: float | None = None) -> dict:
    result = {"state": "unavailable", "handshake_age_seconds": None,
              "received_bytes": 0, "sent_bytes": 0}
    lines = dump.splitlines()
    if not lines:
        return result
    result["state"] = "no_peer"
    if len(lines) < 2:
        return result
    fields = lines[1].split("\t")
    if len(fields) < 8:
        return result
    try:
        handshake = int(fields[4])
        result["received_bytes"] = int(fields[5])
        result["sent_bytes"] = int(fields[6])
    except ValueError:
        return result
    if handshake <= 0:
        result["state"] = "waiting"
        return result
    age = max(0, int((time.time() if now is None else now) - handshake))
    result["handshake_age_seconds"] = age
    result["state"] = "recent" if age <= 180 else "stale"
    return result

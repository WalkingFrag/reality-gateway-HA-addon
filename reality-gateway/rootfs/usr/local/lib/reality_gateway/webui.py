"""Ingress-only status panel and VLESS link management."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit

from .config import load_config, parse_vless_url
from .singbox_config import vless_interface
from .status import config_fingerprint, read_wireguard

STATUS_PATH = Path("/run/reality-gateway/status.json")
VLESS_PATH = Path("/data/vless-exits.json")
AWG_PATH = Path("/data/awg-profiles.json")
OPTIONS_PATH = Path("/data/options.json")
STATIC_PATH = Path("/usr/local/share/reality-gateway/ui")
FILE_LOCK = threading.Lock()


def _command_output(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                check=False, timeout=3)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _read_extras(path: Path) -> list:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("invalid VLESS list")
    return value


def _public_extras(entries: list) -> list:
    return [{"id": item["id"], "label": parse_vless_url(item["url"])["label"]}
            for item in entries]


def _public_awg(entries: list) -> list:
    return [{"id": item["id"], "label": item["name"]} for item in entries]


def _save_extras(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def add_vless(path: Path, url: str) -> dict:
    parsed = parse_vless_url(url)
    with FILE_LOCK:
        entries = _read_extras(path)
        if len(entries) >= 20:
            raise ValueError("maximum of 20 VLESS exits")
        if any(item["url"] == url for item in entries):
            raise ValueError("VLESS exit already exists")
        entry = {"id": "v_" + secrets.token_hex(4), "url": url}
        entries.append(entry)
        _save_extras(path, entries)
    return {"id": entry["id"], "label": parsed["label"]}


def remove_vless(path: Path, exit_id: str) -> list:
    if not re.fullmatch(r"v_[a-z0-9]{1,10}", exit_id):
        raise ValueError("invalid VLESS exit ID")
    with FILE_LOCK:
        entries = _read_extras(path)
        remaining = [item for item in entries if item["id"] != exit_id]
        if len(remaining) == len(entries):
            raise ValueError("VLESS exit not found")
        _save_extras(path, remaining)
    return _public_extras(remaining)


def add_awg(path: Path, options_path: Path, vless_path: Path,
            name: str, profile: str) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48:
        raise ValueError("invalid AWG name")
    if not isinstance(profile, str) or len(profile) > 16384:
        raise ValueError("invalid AWG profile")
    with FILE_LOCK:
        entries = _read_extras(path)
        if len(entries) >= 20:
            raise ValueError("maximum of 20 AWG exits")
        entry = {"id": "w_" + secrets.token_hex(4),
                 "name": name.strip(), "profile": profile}
        candidate = entries + [entry]
        load_config(options_path, vless_path, managed_awg=candidate)
        _save_extras(path, candidate)
    return {"id": entry["id"], "label": entry["name"]}


def remove_awg(path: Path, exit_id: str) -> list:
    if not re.fullmatch(r"w_[a-z0-9]{1,10}", exit_id):
        raise ValueError("invalid AWG exit ID")
    with FILE_LOCK:
        entries = _read_extras(path)
        remaining = [item for item in entries if item["id"] != exit_id]
        if len(remaining) == len(entries):
            raise ValueError("AWG exit not found")
        _save_extras(path, remaining)
    return _public_awg(remaining)


def dashboard_status(status_path: Path, vless_path: Path, wg_dump: str,
                     routes: str, now: float | None = None,
                     awg_path: Path = AWG_PATH) -> dict:
    moment = time.time() if now is None else now
    try:
        runtime = json.loads(status_path.read_text(encoding="utf-8"))
        fresh = moment - runtime["updated_at"] <= 45
    except (OSError, ValueError, KeyError, TypeError):
        runtime = {"current": None, "exits": [], "config_fingerprint": ""}
        fresh = False
    current = runtime.get("current") if fresh else None
    selected = next((item for item in runtime.get("exits", []) if item["id"] == current), None)
    interface = None if selected is None else (
        vless_interface(current) if selected["kind"] == "vless" else "a_" + current)
    route_ok = bool(interface and re.search(
        rf"^default dev {re.escape(interface)}\b.*\bmetric 100\b", routes, re.MULTILINE))
    try:
        extras = _public_extras(_read_extras(vless_path))
        restart_required = fresh and runtime.get("config_fingerprint") != config_fingerprint(vless_path)
    except (OSError, ValueError, KeyError, TypeError):
        extras = []
        restart_required = False
    try:
        awg = _public_awg(_read_extras(awg_path))
        awg_fingerprint = config_fingerprint(awg_path)
        restart_required = restart_required or (fresh and runtime.get(
            "awg_fingerprint", awg_fingerprint) != awg_fingerprint)
    except (OSError, ValueError, KeyError, TypeError):
        awg = []
    return {"online": fresh, "current": current, "route_ok": route_ok,
            "exits": runtime.get("exits", []) if fresh else [],
            "wireguard": read_wireguard(wg_dump, moment),
            "configured_vless": extras, "configured_awg": awg,
            "restart_required": restart_required,
            "updated_at": runtime.get("updated_at") if fresh else None}


class Handler(BaseHTTPRequestHandler):
    server_version = "RealityGatewayUI"

    def _allowed(self) -> bool:
        return self.client_address[0] == "172.30.32.2" or (
            os.environ.get("RG_DEV_WEBUI") == "1" and self.client_address[0] in ("127.0.0.1", "::1"))

    def _reply(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, value: dict | list) -> None:
        self._reply(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._allowed():
            self._json(403, {"error": "forbidden"})
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            self._json(200, dashboard_status(STATUS_PATH, VLESS_PATH,
                                             _command_output(["wg", "show", "wg0", "dump"]),
                                             _command_output(["ip", "route", "show", "table", "100"]),
                                             awg_path=AWG_PATH))
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        if path not in assets:
            self._json(404, {"error": "not found"})
            return
        name, content_type = assets[path]
        self._reply(200, (STATIC_PATH / name).read_bytes(), content_type)

    def do_POST(self) -> None:
        if not self._allowed():
            self._json(403, {"error": "forbidden"})
            return
        path = urlsplit(self.path).path
        if path not in ("/api/vless", "/api/awg") or self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768 or self.headers.get_content_type() != "application/json":
                raise ValueError("invalid request")
            data = json.loads(self.rfile.read(length))
            entry = (add_vless(VLESS_PATH, data["url"]) if path == "/api/vless"
                     else add_awg(AWG_PATH, OPTIONS_PATH, VLESS_PATH, data["name"], data["profile"]))
            self._json(201, entry)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": ("Проверьте VLESS+Reality ссылку и попробуйте снова."
                                       if path == "/api/vless" else
                                       "Проверьте полный профиль AWG3 и попробуйте снова.")})

    def do_DELETE(self) -> None:
        if not self._allowed():
            self._json(403, {"error": "forbidden"})
            return
        path = urlsplit(self.path).path
        if not (path.startswith("/api/vless/") or path.startswith("/api/awg/")) or self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._json(404, {"error": "not found"})
            return
        try:
            self._json(200, remove_vless(VLESS_PATH, path.rsplit("/", 1)[1])
                       if path.startswith("/api/vless/") else remove_awg(AWG_PATH, path.rsplit("/", 1)[1]))
        except ValueError:
            self._json(400, {"error": "Не удалось удалить туннель."})

    def log_message(self, format, *args):
        # Paths can contain user input; avoid including it in persistent add-on logs.
        pass


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()


if __name__ == "__main__":
    main()

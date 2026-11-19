"""Build isolated sing-box TUNs for the legacy and additional VLESS exits."""

import json
from pathlib import Path
import sys

from .config import ExitSpec, load_config


def vless_interface(exit_id: str) -> str:
    return "tun-reality" if exit_id == "vless" else "t_" + exit_id


def build_singbox_config(options: dict, exits: tuple) -> dict:
    vless = [item for item in exits if item.kind == "vless"]
    # The original interface and address are retained for upgrade compatibility.
    vless.sort(key=lambda item: item.id != "vless")
    inbounds, outbounds, rules = [], [], []
    for index, item in enumerate(vless):
        settings = item.vless_settings or {
            "server": options["vless_server"], "port": options["vless_port"],
            "uuid": options["vless_uuid"], "flow": options["vless_flow"],
            "public_key": options["vless_reality_public_key"],
            "short_id": options["vless_reality_short_id"],
            "sni": options["vless_sni"], "fingerprint": "chrome",
        }
        inbound_tag = "tun-" + item.id
        outbound_tag = "out-" + item.id
        inbounds.append({
            "type": "tun", "tag": inbound_tag,
            "interface_name": vless_interface(item.id),
            "address": [f"172.19.{index}.1/30"], "mtu": 1400,
            "auto_route": False, "strict_route": False, "stack": "system",
        })
        outbounds.append({
            "type": "vless", "tag": outbound_tag,
            "server": settings["server"], "server_port": settings["port"],
            "uuid": settings["uuid"], "flow": settings["flow"],
            "tls": {"enabled": True, "server_name": settings["sni"],
                    "utls": {"enabled": True, "fingerprint": settings["fingerprint"]},
                    "reality": {"enabled": True, "public_key": settings["public_key"],
                                "short_id": settings["short_id"]}},
        })
        rules.append({"inbound": [inbound_tag], "outbound": outbound_tag})
    outbounds.append({"type": "direct", "tag": "direct"})
    return {"log": {"level": "info", "timestamp": True},
            "inbounds": inbounds, "outbounds": outbounds, "route": {"rules": rules}}


def main() -> None:
    options_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/data/options.json")
    destination = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/etc/sing-box/config.json")
    try:
        exits = load_config(options_path).exits
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        # The controller already falls back to the legacy VLESS exit when
        # optional exit configuration is invalid. Keep sing-box available too.
        exits = (ExitSpec("vless", "vless", 100),)
    options = json.loads(options_path.read_text(encoding="utf-8"))
    destination.write_text(json.dumps(build_singbox_config(options, exits)), encoding="utf-8")
    destination.chmod(0o600)


if __name__ == "__main__":
    main()

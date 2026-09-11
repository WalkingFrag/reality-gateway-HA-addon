# reality-gateway Home Assistant Add-on Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the already-proven wg-gateway + singbox-reality-tun mechanism as a proper Home Assistant OS add-on: a local git repo Supervisor can add as an add-on store source, buildable entirely on the HA host, configurable via the normal HA UI.

**Architecture:** One Docker image built from `ghcr.io/home-assistant/base:latest` (Alpine, s6-overlay v3 as PID 1). Legacy `cont-init.d`/`services.d` compat layer (still fully supported in current s6-overlay — see resolution note below), not raw `s6-rc.d`. `cont-init.d/10-setup.sh` runs once at container start as a oneshot: generates and persists the WireGuard keypairs to `/data`, brings up the `wg0` kernel interface, and renders the sing-box config from add-on options. `services.d/singbox/run` execs `sing-box run` as the container's supervised long-running process (auto-restarted by s6 on crash). `services.d/routing/run` is a second, independent supervised service: it polls for the `tun-reality` interface (which sing-box creates asynchronously after it starts) and, once present, idempotently applies the `ip_forward`/mangle-mark/policy-route/`DOCKER-USER` rules — then loops, re-applying (cheaply, idempotently) every 60s so it self-heals if sing-box restarts.

**Resolution of the spec's open sequencing question:** researched directly against `github.com/just-containers/s6-overlay` (MOVING-TO-V3.md) and a real multi-service HA add-on (`hassio-addons/app-wireguard`, native `s6-rc.d` with `dependencies.d`). Two findings settle it: (1) all `cont-init.d` scripts still run to completion as a single oneshot *before* any `services.d` longrun starts, in current s6-overlay; (2) even the native `s6-rc.d` dependency graph only orders **service start**, not readiness of an async side-effect created *inside* a running service — so a `tun-reality`-dependent step must poll regardless of which init mechanism is used. Given that, legacy `cont-init.d`/`services.d` (already drafted in the spec's repo layout, and explicitly adequate for "a minimal, functional add-on for a single-user setup") is not meaningfully worse than hand-writing `s6-rc.d` graphs, so this plan keeps the legacy layout and puts the polling in a second `services.d` entry (`routing`), independent of `singbox`.

**Tech Stack:** Docker (`ghcr.io/home-assistant/base:latest`, Alpine/musl), s6-overlay v3 (legacy `cont-init.d`/`services.d`), bashio, sing-box v1.14.0 (static musl binary), `wireguard-tools`, `iptables`, `iproute2`.

**Spec:** `docs/superpowers/specs/2026-09-11-reality-gateway-addon-design.md`

## Global Constraints

- No router-side automation or credentials in the add-on (spec Scope).
- WireGuard key material is generated once and persisted in `/data`, never an add-on option (spec Configuration).
- All routing/iptables setup must be idempotent — check-before-add, safe to re-run on every container/service restart (spec Add-on internals).
- Default option values must exactly match the spec's already-verified values (spec Configuration table) — do not invent different defaults.
- No `build.yaml` / `ARG BUILD_FROM` — current Supervisor (2026.04.0+) removed the implicit `BUILD_FROM` arg; the Dockerfile must `FROM ghcr.io/home-assistant/base:latest` directly. `BUILD_ARCH` is still provided as a build arg.
- No add-on icon/logo, no translations, no multi-exit-server support (spec Non-goals).

---

### Task 1: Repository scaffold — manifests and docs skeleton

**Files:**
- Create: `repository.yaml`
- Create: `reality-gateway/config.yaml`
- Create: `reality-gateway/CHANGELOG.md`
- Create: `reality-gateway/README.md`
- Test: `scratch/test_yaml_scaffold.py` (temporary, in scratchpad — not committed)

**Interfaces:**
- Produces: the 10 option names/types every later task's scripts read via `bashio::config "<name>"`: `vless_server` (str), `vless_port` (port), `vless_uuid` (str), `vless_flow` (str), `vless_reality_public_key` (str), `vless_reality_short_id` (str), `vless_sni` (str), `wg_listen_port` (port), `wg_server_address` (str), `wg_peer_allowed_ip` (str).

- [ ] **Step 1: Write `repository.yaml`**

```yaml
name: reality-gateway Add-ons
url: "https://github.com/CHANGEME/HA_VLESS"
maintainer: Andrew D <itech.aqua@gmail.com>
```

- [ ] **Step 2: Write `reality-gateway/config.yaml`**

```yaml
name: "Reality Gateway"
version: "0.1.0"
slug: reality_gateway
description: "VLESS+Reality VPN fallback gateway: WireGuard server + sing-box TUN client"
arch:
  - amd64
  - aarch64
  - armv7
host_network: true
privileged:
  - NET_ADMIN
devices:
  - /dev/net/tun
init: false
options:
  vless_server: REDACTED-see-VPS-notes
  vless_port: 444
  vless_uuid: "REDACTED-see-VPS-notes"
  vless_flow: xtls-rprx-vision
  vless_reality_public_key: "QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M"
  vless_reality_short_id: "REDACTED-see-VPS-notes"
  vless_sni: www.googletagmanager.com
  wg_listen_port: 51821
  wg_server_address: 10.20.30.1/24
  wg_peer_allowed_ip: 10.20.30.2/32
schema:
  vless_server: str
  vless_port: port
  vless_uuid: str
  vless_flow: str
  vless_reality_public_key: str
  vless_reality_short_id: str
  vless_sni: str
  wg_listen_port: port
  wg_server_address: str
  wg_peer_allowed_ip: str
```

`init: false` because the base image already provides s6-overlay as PID 1 — a second init layer is unnecessary and is the documented convention for add-ons built on `ghcr.io/home-assistant/base`.

- [ ] **Step 3: Write `reality-gateway/CHANGELOG.md`**

```markdown
# Changelog

## 0.1.0

- Initial release: WireGuard server + sing-box VLESS+Reality TUN client, packaged as a Home Assistant add-on.
```

- [ ] **Step 4: Write `reality-gateway/README.md` stub**

```markdown
# Reality Gateway

VLESS+Reality VPN fallback gateway for Home Assistant OS. Packages a
WireGuard server (`wg0`) and a sing-box TUN client (`tun-reality`) that
forwards WireGuard traffic out over a VLESS+Reality connection, for use
when the primary VPN egress is unavailable.

See `docs/superpowers/specs/2026-09-11-reality-gateway-addon-design.md`
in this repository for the full design and the router-side manual setup
this add-on assumes.

## Installation

1. In Home Assistant: Settings → Add-ons → Add-on Store → ⋮ → Repositories → add this repo's git URL.
2. Install "Reality Gateway" from the store.
3. Configure the options (defaults match the already-verified VLESS/WireGuard values; only change if pointing at a different exit server).
4. Start the add-on. Check the log for the one-time router-side WireGuard values (router private key, router public key, PSK, suggested AllowedIPs) and enter them into the Keenetic router's `Wireguard2` interface manually.
```

- [ ] **Step 5: Validate YAML and required fields**

```python
# scratch/test_yaml_scaffold.py
import yaml

repo = yaml.safe_load(open("repository.yaml"))
assert {"name", "url", "maintainer"} <= repo.keys()

cfg = yaml.safe_load(open("reality-gateway/config.yaml"))
required = {"name", "version", "slug", "arch", "host_network", "privileged", "devices", "options", "schema"}
assert required <= cfg.keys(), required - cfg.keys()
assert cfg["host_network"] is True
assert cfg["privileged"] == ["NET_ADMIN"]
assert cfg["devices"] == ["/dev/net/tun"]
expected_options = {
    "vless_server", "vless_port", "vless_uuid", "vless_flow",
    "vless_reality_public_key", "vless_reality_short_id", "vless_sni",
    "wg_listen_port", "wg_server_address", "wg_peer_allowed_ip",
}
assert set(cfg["options"].keys()) == expected_options
assert set(cfg["schema"].keys()) == expected_options
print("OK")
```

Run: `python scratch/test_yaml_scaffold.py` (from the repo root)
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add repository.yaml reality-gateway/config.yaml reality-gateway/CHANGELOG.md reality-gateway/README.md
git commit -m "Add reality-gateway add-on repository scaffold"
```

---

### Task 2: Dockerfile — base image, packages, sing-box binary

**Files:**
- Create: `reality-gateway/Dockerfile`

**Interfaces:**
- Produces: an image with `sing-box`, `wg`/`wg-quick`, `iptables`, `ip` on `PATH`, ready for `rootfs/` to be layered on top in Task 7.

- [ ] **Step 1: Write `reality-gateway/Dockerfile`**

```dockerfile
FROM ghcr.io/home-assistant/base:latest

ARG BUILD_ARCH=amd64
ENV SING_BOX_VERSION=1.14.0

RUN apk add --no-cache \
        wireguard-tools \
        iptables \
        iproute2 \
        curl \
    && case "${BUILD_ARCH}" in \
        amd64)  SING_BOX_ARCH="amd64" ;; \
        aarch64) SING_BOX_ARCH="arm64" ;; \
        armv7)  SING_BOX_ARCH="armv7" ;; \
        *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/sing-box.tar.gz \
        "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}-musl.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && mv "/tmp/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}-musl/sing-box" /usr/local/bin/sing-box \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box.tar.gz "/tmp/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}-musl"
```

- [ ] **Step 2: Build the image locally**

Run: `docker build --build-arg BUILD_ARCH=amd64 -t reality-gateway-test ./reality-gateway`
Expected: builds successfully, ends with `Successfully tagged reality-gateway-test:latest` (or the buildkit equivalent final `naming to ... done`).

- [ ] **Step 3: Verify the installed binaries work**

Run: `docker run --rm reality-gateway-test sing-box version`
Expected: prints `sing-box version 1.14.0` (or similar version banner), exit code 0.

Run: `docker run --rm reality-gateway-test wg --version`
Expected: prints a `wireguard-tools` version string, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add reality-gateway/Dockerfile
git commit -m "Add reality-gateway Dockerfile: base image, sing-box, wireguard-tools"
```

---

### Task 3: cont-init.d — WireGuard key generation and persistence

**Files:**
- Create: `reality-gateway/rootfs/etc/cont-init.d/10-setup.sh`

**Interfaces:**
- Produces: `/data/wg-keys.env` with `SERVER_PRIVATE_KEY`, `SERVER_PUBLIC_KEY`, `ROUTER_PRIVATE_KEY`, `ROUTER_PUBLIC_KEY`, `PSK` — consumed by Task 4 (rendering `wg0`'s config) and by this same script's own router-side log output.
- Consumes (in later steps of this same file, added in Task 4): nothing yet — this task only adds the key-generation function and its call.

- [ ] **Step 1: Write the key-generation portion of `10-setup.sh`**

```bash
#!/command/with-contenv bashio
# reality-gateway cont-init: one-shot setup (runs once per container start)
set -euo pipefail

KEYS_FILE=/data/wg-keys.env

generate_keys_if_needed() {
    if [[ -f "${KEYS_FILE}" ]]; then
        bashio::log.info "WireGuard keys already exist in ${KEYS_FILE}, reusing them"
        return 0
    fi

    bashio::log.info "Generating WireGuard keypairs (first run)"
    local server_private_key router_private_key psk
    server_private_key=$(wg genkey)
    router_private_key=$(wg genkey)
    psk=$(wg genpsk)

    {
        echo "SERVER_PRIVATE_KEY=${server_private_key}"
        echo "SERVER_PUBLIC_KEY=$(echo "${server_private_key}" | wg pubkey)"
        echo "ROUTER_PRIVATE_KEY=${router_private_key}"
        echo "ROUTER_PUBLIC_KEY=$(echo "${router_private_key}" | wg pubkey)"
        echo "PSK=${psk}"
    } > "${KEYS_FILE}"
    chmod 600 "${KEYS_FILE}"
}

log_router_values() {
    # shellcheck disable=SC1090
    source "${KEYS_FILE}"
    bashio::log.notice "=== Router-side WireGuard values (enter these into the Keenetic Wireguard2 interface) ==="
    bashio::log.notice "Router private key: ${ROUTER_PRIVATE_KEY}"
    bashio::log.notice "Router public key:  ${ROUTER_PUBLIC_KEY}"
    bashio::log.notice "Preshared key:      ${PSK}"
    bashio::log.notice "Peer (this add-on) public key: ${SERVER_PUBLIC_KEY}"
    bashio::log.notice "Suggested AllowedIPs on the router: $(bashio::config 'wg_peer_allowed_ip')"
    bashio::log.notice "=========================================================================="
}

generate_keys_if_needed
log_router_values
```

- [ ] **Step 2: Check the script's syntax**

Run: `bash -n reality-gateway/rootfs/etc/cont-init.d/10-setup.sh`
Expected: no output, exit code 0.

- [ ] **Step 3: Test key generation and idempotency without privileges**

This only needs `wg genkey`/`wg pubkey`/`wg genpsk` and file I/O — no `NET_ADMIN`, so it runs in a plain container using the image built in Task 2.

`bashio` calls inside the real script require the real bashio library (only present via the base image's `with-contenv bashio` wrapper) — so test the pure key-generation logic directly, extracted into a standalone check with no bashio dependency:

```bash
mkdir -p /tmp/reality-gateway-data-test
cat > /tmp/reality-gateway-data-test/keys_test.sh <<'EOS'
set -euo pipefail
KEYS_FILE=/data/wg-keys.env
generate_keys_if_needed() {
    if [[ -f "${KEYS_FILE}" ]]; then
        echo "reused"
        return 0
    fi
    local server_private_key router_private_key psk
    server_private_key=$(wg genkey)
    router_private_key=$(wg genkey)
    psk=$(wg genpsk)
    {
        echo "SERVER_PRIVATE_KEY=${server_private_key}"
        echo "SERVER_PUBLIC_KEY=$(echo "${server_private_key}" | wg pubkey)"
        echo "ROUTER_PRIVATE_KEY=${router_private_key}"
        echo "ROUTER_PUBLIC_KEY=$(echo "${router_private_key}" | wg pubkey)"
        echo "PSK=${psk}"
    } > "${KEYS_FILE}"
    chmod 600 "${KEYS_FILE}"
    echo "generated"
}
generate_keys_if_needed
EOS
docker run --rm -v /tmp/reality-gateway-data-test:/data \
  reality-gateway-test bash /data/keys_test.sh
# run a second time to check idempotency
docker run --rm -v /tmp/reality-gateway-data-test:/data \
  reality-gateway-test bash /data/keys_test.sh
cat /tmp/reality-gateway-data-test/wg-keys.env
```

Expected: first run prints `generated`, second run prints `reused`, and `wg-keys.env` contains all 5 `KEY=value` lines with non-empty base64-looking values on both runs (i.e. the second run did not overwrite them — diff the file's mtime or content before/after to confirm).

- [ ] **Step 4: Clean up the test scratch dir**

Run: `rm -rf /tmp/reality-gateway-data-test`

- [ ] **Step 5: Commit**

```bash
chmod +x reality-gateway/rootfs/etc/cont-init.d/10-setup.sh
git add reality-gateway/rootfs/etc/cont-init.d/10-setup.sh
git commit -m "Add cont-init.d WireGuard key generation and persistence"
```

---

### Task 4: cont-init.d — wg0 interface and sing-box config rendering

**Files:**
- Modify: `reality-gateway/rootfs/etc/cont-init.d/10-setup.sh` (append)

**Interfaces:**
- Consumes: `${KEYS_FILE}` from Task 3 (`SERVER_PRIVATE_KEY`, `ROUTER_PUBLIC_KEY`, `PSK`); `bashio::config` values `wg_listen_port`, `wg_server_address`, `wg_peer_allowed_ip`, `vless_server`, `vless_port`, `vless_uuid`, `vless_flow`, `vless_reality_public_key`, `vless_reality_short_id`, `vless_sni`.
- Produces: the `wg0` kernel interface, up and configured; `/etc/sing-box/config.json` — consumed by Task 5's `sing-box run`.

- [ ] **Step 1: Append the wg0 and sing-box rendering functions**

```bash
setup_wg0() {
    # shellcheck disable=SC1090
    source "${KEYS_FILE}"
    local listen_port server_address peer_allowed_ip
    listen_port=$(bashio::config 'wg_listen_port')
    server_address=$(bashio::config 'wg_server_address')
    peer_allowed_ip=$(bashio::config 'wg_peer_allowed_ip')

    mkdir -p /etc/wireguard
    cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
PrivateKey = ${SERVER_PRIVATE_KEY}
ListenPort = ${listen_port}

[Peer]
PublicKey = ${ROUTER_PUBLIC_KEY}
PresharedKey = ${PSK}
AllowedIPs = ${peer_allowed_ip}
EOF
    chmod 600 /etc/wireguard/wg0.conf

    if ! ip link show wg0 &>/dev/null; then
        bashio::log.info "Creating wg0 interface"
        ip link add wg0 type wireguard
        ip addr add "${server_address}" dev wg0
    fi
    wg setconf wg0 /etc/wireguard/wg0.conf
    ip link set wg0 up
    bashio::log.info "wg0 is up (${server_address}, listening on ${listen_port})"
}

render_singbox_config() {
    mkdir -p /etc/sing-box
    cat > /etc/sing-box/config.json <<EOF
{
  "log": { "level": "info", "timestamp": true },
  "inbounds": [
    {
      "type": "tun",
      "tag": "tun-reality",
      "interface_name": "tun-reality",
      "address": ["172.19.0.1/30"],
      "mtu": 9000,
      "auto_route": false,
      "strict_route": false,
      "stack": "system"
    }
  ],
  "outbounds": [
    {
      "type": "vless",
      "tag": "vless-out",
      "server": "$(bashio::config 'vless_server')",
      "server_port": $(bashio::config 'vless_port'),
      "uuid": "$(bashio::config 'vless_uuid')",
      "flow": "$(bashio::config 'vless_flow')",
      "tls": {
        "enabled": true,
        "server_name": "$(bashio::config 'vless_sni')",
        "reality": {
          "enabled": true,
          "public_key": "$(bashio::config 'vless_reality_public_key')",
          "short_id": "$(bashio::config 'vless_reality_short_id')"
        }
      }
    },
    { "type": "direct", "tag": "direct" }
  ],
  "route": {
    "rules": [
      { "inbound": ["tun-reality"], "outbound": "vless-out" }
    ]
  }
}
EOF
    bashio::log.info "Rendered /etc/sing-box/config.json"
}

setup_wg0
render_singbox_config
```

`auto_route: false` / `strict_route: false` on the tun inbound are deliberate: sing-box must not touch host routing itself — Task 6's `routing/run` owns all policy routing via the fwmark table, so sing-box only needs to create the interface and forward what's sent to it.

- [ ] **Step 2: Check syntax**

Run: `bash -n reality-gateway/rootfs/etc/cont-init.d/10-setup.sh`
Expected: no output, exit code 0.

- [ ] **Step 3: Test sing-box config rendering in isolation (no NET_ADMIN needed)**

The `render_singbox_config` function only does string templating — test it standalone with mock `bashio::config` and validate the JSON is well-formed:

```bash
cat > /tmp/render_test.sh <<'EOS'
set -euo pipefail
bashio() { :; }
bashio::config() {
    case "$1" in
        vless_server) echo "REDACTED-see-VPS-notes" ;;
        vless_port) echo "444" ;;
        vless_uuid) echo "REDACTED-see-VPS-notes" ;;
        vless_flow) echo "xtls-rprx-vision" ;;
        vless_reality_public_key) echo "QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M" ;;
        vless_reality_short_id) echo "REDACTED-see-VPS-notes" ;;
        vless_sni) echo "www.googletagmanager.com" ;;
    esac
}
bashio::log.info() { :; }
EOS
sed -n '/^render_singbox_config()/,/^}/p' reality-gateway/rootfs/etc/cont-init.d/10-setup.sh >> /tmp/render_test.sh
echo 'render_singbox_config' >> /tmp/render_test.sh
echo 'cat /etc/sing-box/config.json' >> /tmp/render_test.sh

# The image itself has no python3 (Alpine, only the packages from Task 2) —
# render inside the container, capture the JSON to the host, validate with
# the host's own Python instead.
docker run --rm -v /tmp/render_test.sh:/render_test.sh:ro reality-gateway-test \
  bash /render_test.sh > /tmp/rendered_config.json
python3 -m json.tool /tmp/rendered_config.json > /dev/null
python3 -c "
import json
cfg = json.load(open('/tmp/rendered_config.json'))
assert cfg['outbounds'][0]['server'] == 'REDACTED-see-VPS-notes'
assert cfg['inbounds'][0]['auto_route'] is False
print('OK')
"
```

Expected: `python3 -m json.tool` exits 0 (valid JSON), and the assertions print `OK`.

- [ ] **Step 4: Note the untestable portion**

`setup_wg0`'s `ip link add wg0 type wireguard` requires the WireGuard kernel module and `CAP_NET_ADMIN` inside the container — not reliably available in this local Docker Desktop/WSL2 dev environment. This is not verified until Task 9 (deploy to the real HA host). Record this explicitly rather than claiming it passed a test it didn't run against.

- [ ] **Step 5: Clean up**

Run: `rm -f /tmp/render_test.sh`

- [ ] **Step 6: Commit**

```bash
git add reality-gateway/rootfs/etc/cont-init.d/10-setup.sh
git commit -m "Add wg0 interface setup and sing-box config rendering to cont-init.d"
```

---

### Task 5: services.d/singbox — supervised sing-box process

**Files:**
- Create: `reality-gateway/rootfs/etc/services.d/singbox/run`

**Interfaces:**
- Consumes: `/etc/sing-box/config.json` (Task 4).
- Produces: the running `sing-box` process and the `tun-reality` interface it creates — consumed by Task 6's polling.

- [ ] **Step 1: Write the run script**

```bash
#!/command/with-contenv bashio
# reality-gateway: sing-box supervised service
exec sing-box run -c /etc/sing-box/config.json
```

- [ ] **Step 2: Check syntax and executable bit**

Run: `bash -n reality-gateway/rootfs/etc/services.d/singbox/run`
Expected: no output, exit code 0.

Run: `chmod +x reality-gateway/rootfs/etc/services.d/singbox/run`

- [ ] **Step 3: Verify sing-box accepts the rendered config**

Using the config produced by Task 4's test, do a config-only syntax check (sing-box supports `check`, which validates without running):

```bash
mkdir -p /tmp/singbox-check
cat > /tmp/singbox-check/config.json <<'EOF'
{
  "log": { "level": "info", "timestamp": true },
  "inbounds": [
    {
      "type": "tun",
      "tag": "tun-reality",
      "interface_name": "tun-reality",
      "address": ["172.19.0.1/30"],
      "mtu": 9000,
      "auto_route": false,
      "strict_route": false,
      "stack": "system"
    }
  ],
  "outbounds": [
    {
      "type": "vless",
      "tag": "vless-out",
      "server": "REDACTED-see-VPS-notes",
      "server_port": 444,
      "uuid": "REDACTED-see-VPS-notes",
      "flow": "xtls-rprx-vision",
      "tls": {
        "enabled": true,
        "server_name": "www.googletagmanager.com",
        "reality": {
          "enabled": true,
          "public_key": "QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M",
          "short_id": "REDACTED-see-VPS-notes"
        }
      }
    },
    { "type": "direct", "tag": "direct" }
  ],
  "route": {
    "rules": [
      { "inbound": ["tun-reality"], "outbound": "vless-out" }
    ]
  }
}
EOF
docker run --rm -v /tmp/singbox-check/config.json:/config.json:ro reality-gateway-test sing-box check -c /config.json
```

Expected: exit code 0, no error output (sing-box's `check` command validates config schema without needing `/dev/net/tun` or `NET_ADMIN`).

- [ ] **Step 4: Clean up**

Run: `rm -rf /tmp/singbox-check`

- [ ] **Step 5: Commit**

```bash
git add reality-gateway/rootfs/etc/services.d/singbox/run
git commit -m "Add services.d/singbox supervised run script"
```

---

### Task 6: services.d/routing — wait for tun-reality, apply idempotent routing

**Files:**
- Create: `reality-gateway/rootfs/etc/services.d/routing/run`

**Interfaces:**
- Consumes: the `wg0` interface (Task 4) and `tun-reality` (Task 5, created by sing-box after it starts).
- Produces: the fwmark/policy-route/`DOCKER-USER` rules that make wg0↔tun-reality traffic actually flow.

- [ ] **Step 1: Write the run script**

```bash
#!/command/with-contenv bashio
# reality-gateway: routing supervised service
# Waits for sing-box's tun-reality interface, then idempotently applies
# the policy routing that sends wg0 traffic out via tun-reality.
set -euo pipefail

MAX_RETRIES=30
RETRY_INTERVAL=2
REAPPLY_INTERVAL=60

wait_for_tun() {
    local i=0
    while (( i < MAX_RETRIES )); do
        if ip link show tun-reality &>/dev/null; then
            return 0
        fi
        sleep "${RETRY_INTERVAL}"
        ((i++))
    done
    return 1
}

apply_routing_rules() {
    sysctl -w net.ipv4.ip_forward=1 >/dev/null

    if ! iptables -t mangle -C PREROUTING -i wg0 -j MARK --set-mark 100 2>/dev/null; then
        iptables -t mangle -A PREROUTING -i wg0 -j MARK --set-mark 100
    fi

    if ! ip rule show | grep -q 'fwmark 0x64 lookup 100'; then
        ip rule add fwmark 100 table 100
    fi

    ip route replace default dev tun-reality table 100

    if ! iptables -C DOCKER-USER -i wg0 -o tun-reality -j ACCEPT 2>/dev/null; then
        iptables -I DOCKER-USER -i wg0 -o tun-reality -j ACCEPT
    fi
    if ! iptables -C DOCKER-USER -i tun-reality -o wg0 -j ACCEPT 2>/dev/null; then
        iptables -I DOCKER-USER -i tun-reality -o wg0 -j ACCEPT
    fi
}

if ! wait_for_tun; then
    bashio::log.error "tun-reality did not appear after $(( MAX_RETRIES * RETRY_INTERVAL ))s — sing-box may have failed to start; check its log"
    exit 1
fi

bashio::log.info "tun-reality is up, applying routing rules"
while true; do
    apply_routing_rules
    sleep "${REAPPLY_INTERVAL}"
done
```

- [ ] **Step 2: Check syntax and executable bit**

Run: `bash -n reality-gateway/rootfs/etc/services.d/routing/run`
Expected: no output, exit code 0.

Run: `chmod +x reality-gateway/rootfs/etc/services.d/routing/run`

- [ ] **Step 3: Unit-test the idempotency logic with stubbed `ip`/`iptables`**

`apply_routing_rules` is pure bash calling only `ip`, `iptables`, `sysctl` (no `bashio` inside it) — stub those three commands as shell functions and extract just `apply_routing_rules`'s body from the real file with `sed`, rather than sourcing the whole file (which would hang on its own trailing `while true` loop):

```bash
mkdir -p /tmp/routing-test
cat > /tmp/routing-test/run_once.sh <<'EOS'
set -euo pipefail
bashio::log.info() { :; }
bashio::log.error() { :; }
ip() {
    echo "ip $*" >> /tmp/routing-test/calls.log
    [[ "$1 $2" == "rule show" ]] && cat /tmp/routing-test/rule_state.txt 2>/dev/null
    return 0
}
iptables() {
    echo "iptables $*" >> /tmp/routing-test/calls.log
    if [[ "$1 $2" == "-t mangle" && "$3" == "-C" ]]; then
        [[ -f /tmp/routing-test/mark_state.txt ]] && return 0 || return 1
    fi
    if [[ "$1 $2" == "-t mangle" && "$3" == "-A" ]]; then : > /tmp/routing-test/mark_state.txt; return 0; fi
    if [[ "$1" == "-C" ]]; then
        grep -qxF "$*" /tmp/routing-test/docker_user_state.txt 2>/dev/null && return 0 || return 1
    fi
    if [[ "$1" == "-I" ]]; then echo "-C ${*:2}" >> /tmp/routing-test/docker_user_state.txt; return 0; fi
    return 0
}
sysctl() { :; }
sed -n '/^apply_routing_rules()/,/^}/p' /repo/reality-gateway/rootfs/etc/services.d/routing/run > /tmp/apply_fn.sh
source /tmp/apply_fn.sh
apply_routing_rules
EOS
rm -f /tmp/routing-test/calls.log /tmp/routing-test/mark_state.txt /tmp/routing-test/docker_user_state.txt
docker run --rm -v "$(pwd):/repo" -v /tmp/routing-test:/tmp/routing-test bash:5 bash /tmp/routing-test/run_once.sh
FIRST_CALLS=$(wc -l < /tmp/routing-test/calls.log)
docker run --rm -v "$(pwd):/repo" -v /tmp/routing-test:/tmp/routing-test bash:5 bash /tmp/routing-test/run_once.sh
SECOND_CALLS=$(wc -l < /tmp/routing-test/calls.log)
echo "first cumulative calls: $FIRST_CALLS, after second run: $SECOND_CALLS"
grep -c '^iptables -t mangle -A' /tmp/routing-test/calls.log
```

Expected: `grep -c '^iptables -t mangle -A'` returns `1` even after two runs (the mark rule was added once, then skipped on the second run because the `-C` check stub reports it already exists) — confirming the idempotency logic actually skips re-adding.

- [ ] **Step 4: Clean up**

Run: `rm -rf /tmp/routing-test`

- [ ] **Step 5: Commit**

```bash
git add reality-gateway/rootfs/etc/services.d/routing/run
git commit -m "Add services.d/routing: wait for tun-reality, idempotent routing setup"
```

---

### Task 7: Wire rootfs into the Dockerfile, full local build

**Files:**
- Modify: `reality-gateway/Dockerfile`

**Interfaces:**
- Consumes: everything from Tasks 3–6 (`rootfs/etc/cont-init.d/10-setup.sh`, `rootfs/etc/services.d/singbox/run`, `rootfs/etc/services.d/routing/run`).

- [ ] **Step 1: Append the rootfs COPY to the Dockerfile**

```dockerfile

COPY rootfs /
RUN chmod +x /etc/cont-init.d/10-setup.sh \
    /etc/services.d/singbox/run \
    /etc/services.d/routing/run
```

- [ ] **Step 2: Full local build**

Run: `docker build --build-arg BUILD_ARCH=amd64 -t reality-gateway-test ./reality-gateway`
Expected: builds successfully; final layer includes `/etc/cont-init.d/10-setup.sh` and both `services.d` run scripts.

- [ ] **Step 3: Confirm the files landed correctly and are executable**

Run:
```bash
docker run --rm reality-gateway-test ls -la /etc/cont-init.d/10-setup.sh /etc/services.d/singbox/run /etc/services.d/routing/run
```
Expected: all three listed with the executable bit set (`-rwxr-xr-x` or similar), exit code 0.

- [ ] **Step 4: Attempt a privileged smoke test (best-effort — may not work on this dev machine)**

```bash
docker run --rm --cap-add=NET_ADMIN --device=/dev/net/tun \
  -e SUPERVISOR_TOKEN=test \
  reality-gateway-test bash -c 'wg genkey | wg pubkey' && echo "wg tools OK under --cap-add=NET_ADMIN"
```

Expected: either succeeds (confirms basic WireGuard tooling works under the granted capability in this environment), or fails with a kernel-module-related error — if it fails, record that as an environment limitation (Docker Desktop/WSL2 kernel likely lacks the WireGuard module or `/dev/net/tun` isn't exposed the same way), not a code defect. Full runtime verification is Task 9, against the real HA host.

- [ ] **Step 5: Commit**

```bash
git add reality-gateway/Dockerfile
git commit -m "Wire rootfs into Dockerfile image"
```

---

### Task 8: README completion

**Files:**
- Modify: `reality-gateway/README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Expand the README with the full options table and update flow**

```markdown

## Configuration options

| Option | Default | Description |
|---|---|---|
| `vless_server` | `REDACTED-see-VPS-notes` | VLESS+Reality exit server IP |
| `vless_port` | `444` | VLESS+Reality exit server port |
| `vless_uuid` | (see config.yaml) | Xray client UUID on the exit server |
| `vless_flow` | `xtls-rprx-vision` | XTLS flow control |
| `vless_reality_public_key` | (see config.yaml) | Reality public key |
| `vless_reality_short_id` | (see config.yaml) | Reality short ID |
| `vless_sni` | `www.googletagmanager.com` | Reality SNI camouflage domain |
| `wg_listen_port` | `51821` | UDP port the add-on's WireGuard server listens on |
| `wg_server_address` | `10.20.30.1/24` | `wg0`'s address on the add-on side |
| `wg_peer_allowed_ip` | `10.20.30.2/32` | The router's address inside the WireGuard tunnel |

WireGuard key material is **not** an option — it's generated once on
first start and persisted in `/data`, surviving add-on updates and
restarts (only cleared by an explicit uninstall).

## Updating

1. Edit code in this repo.
2. Bump `version` in `reality-gateway/config.yaml`.
3. Commit and push.
4. In Home Assistant: Settings → Add-ons → Add-on Store → this add-on shows an update → click Update (Supervisor rebuilds the image locally on the HA host).

## Out of scope

The Keenetic router side (creating the `Wireguard2` interface, setting
`ip.global`, and flipping the `dns-proxy route` domain-list entry) stays
a manual step — this add-on never holds router admin credentials. See
`docs/superpowers/specs/2026-09-11-reality-gateway-addon-design.md` for
the full background.
```

- [ ] **Step 2: Review for accuracy against config.yaml**

Run:
```python
import yaml
cfg = yaml.safe_load(open("reality-gateway/config.yaml"))
readme = open("reality-gateway/README.md").read()
for opt in cfg["options"]:
    assert f"`{opt}`" in readme, f"missing {opt} in README"
print("OK")
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add reality-gateway/README.md
git commit -m "Document configuration options and update flow in README"
```

---

### Task 9: Deploy to the real Home Assistant host and verify

**Files:** none (deployment/verification only — no code changes expected unless verification surfaces a bug, in which case fix it in the relevant task's file and repeat this task).

**Interfaces:** none — this is the end-to-end acceptance check for the whole plan.

- [ ] **Step 1: Push the repo to its git remote**

Confirm `repository.yaml`'s `url` field matches the actual remote before pushing (fix the `CHANGEME` placeholder set in Task 1 to the real repo URL once it exists).

- [ ] **Step 2: Add the repository to Supervisor**

In HA: Settings → Add-ons → Add-on Store → ⋮ → Repositories → paste the repo URL → Add.

- [ ] **Step 3: Install and start the add-on**

Settings → Add-ons → Add-on Store → "Reality Gateway" → Install. Leave options at their defaults (they match the already-verified manual setup). Start the add-on.

- [ ] **Step 4: Check the add-on log**

Expected log lines, in order: WireGuard key generation (first start only) or "reusing them" (subsequent starts), the router-side values block, "wg0 is up", sing-box startup (no fatal errors), "tun-reality is up, applying routing rules".

If the router-side keys shown differ from what the Keenetic router is currently configured with (from the prior manual build), update the router's `Wireguard2` interface peer settings to match — this is the one manual, out-of-scope step per the spec.

- [ ] **Step 5: Verify interfaces and routing on the HA host**

Via HA's own SSH/terminal add-on or `docker exec` into the reality-gateway container:
```bash
ip link show wg0
ip link show tun-reality
iptables -t mangle -L PREROUTING -n
ip rule show
ip route show table 100
iptables -L DOCKER-USER -n
```
Expected: both interfaces up, the mangle rule present exactly once, the fwmark rule present exactly once, a default route via `tun-reality` in table 100, and both `DOCKER-USER` ACCEPT rules present exactly once.

- [ ] **Step 6: Verify actual traffic flow**

From a device connected to the router's `Wireguard2` fallback tunnel (or by temporarily flipping the router's `dns-proxy route` domain-list entry to this fallback, per the router-side manual step that stays out of scope for this add-on), confirm outbound traffic reaches the internet, and check the VPS's Xray/sing-box server log for a new connection from this add-on's UUID.

- [ ] **Step 7: Verify idempotency across a restart**

Restart the add-on from the HA UI. Re-run the Step 5 commands. Expected: identical output — no duplicated iptables rules, no duplicated `ip rule` entries, and `/data/wg-keys.env` unchanged (same keys, so the router doesn't need reconfiguring after ordinary add-on restarts/updates).

- [ ] **Step 8: Record the outcome**

Update `reality-gateway/CHANGELOG.md` if any fix was needed during this deployment pass, bump `version` accordingly, commit and push.

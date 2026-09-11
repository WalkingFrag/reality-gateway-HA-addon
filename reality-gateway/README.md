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
3. Configure the options. `vless_server`, `vless_uuid`, and `vless_reality_short_id` have no default and are **required** — get these from your VLESS+Reality exit server's own config (they identify and authenticate against that specific server, so they're deliberately not shipped as defaults in this public repo). The rest default to already-verified values; only change them if you need different WireGuard addressing or a different Reality SNI.
4. Start the add-on. Check the log for the one-time router-side WireGuard values (router private key, router public key, PSK, suggested AllowedIPs) and enter them into the Keenetic router's `Wireguard2` interface manually.

## Configuration options

| Option | Default | Description |
|---|---|---|
| `vless_server` | **required, no default** | VLESS+Reality exit server IP or hostname |
| `vless_port` | `444` | VLESS+Reality exit server port |
| `vless_uuid` | **required, no default** | Xray client UUID on the exit server — this is a credential, not a public value |
| `vless_flow` | `xtls-rprx-vision` | XTLS flow control |
| `vless_reality_public_key` | `QqAo_aC2hr-1ThVR-HFu4Vrn6mm4PKA4esLIhrgq42M` | Reality public key (this is the server's public key — safe to publish, unlike the UUID/short ID) |
| `vless_reality_short_id` | **required, no default** | Reality short ID — part of Reality's anti-probing defense, treat as sensitive |
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

## Host network state

This add-on modifies **host** network state directly, not just container
state:

- `wg0` and the policy routing rules (mangle mark, `ip rule`, `ip route`,
  `DOCKER-USER` accepts) all live in the Home Assistant host's network
  namespace, because the add-on runs with `host_network: true`. Stopping
  the add-on does **not** revert any of this — `wg0`, the iptables rules,
  and the `ip rule`/table 100 entries all persist until the host reboots
  or they're removed manually. A full uninstall/teardown flow that cleans
  this up automatically is deferred to a future release.
- The policy routing uses a hardcoded firewall mark and routing table:
  `fwmark 100` / `table 100`. These are not configurable. If anything else
  on the Home Assistant host ever uses table 100 for its own routing, it
  will silently collide with this add-on's rules — worth checking before
  adding other policy routing on the same host.
- During any window where the sing-box tunnel (`tun-reality`) isn't up yet
  (add-on starting) or has gone away (add-on stopped or crashed) while the
  `wg0` mangle rule and `ip rule fwmark 100 table 100` are still in place,
  the routing service seeds a `blackhole` default route in table 100 as a
  safety floor. This makes WireGuard traffic get dropped instead of
  leaking out the host's normal WAN in the clear — but it only closes that
  traffic-leak window; it does not remove the interface or rules
  themselves (see the point above).
- `wg_listen_port` is bound directly on the Home Assistant host (again
  because of `host_network: true`), not inside an isolated container
  network — it must be reachable from the router at the host's IP.

## Out of scope

The Keenetic router side (creating the `Wireguard2` interface, setting
`ip.global`, and flipping the `dns-proxy route` domain-list entry) stays
a manual step — this add-on never holds router admin credentials. See
`docs/superpowers/specs/2026-09-11-reality-gateway-addon-design.md` for
the full background.

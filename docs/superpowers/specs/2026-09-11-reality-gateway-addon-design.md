# reality-gateway Home Assistant add-on — design

## Purpose

Package the VLESS+Reality VPN fallback gateway — currently two manually
`docker run`-deployed containers on Home Assistant OS (`wg-gateway`, a
kernel WireGuard server, and `singbox-reality-tun`, a sing-box TUN client
forwarding to a VLESS+Reality server) — into a proper Home Assistant
add-on. Goals: visible and manageable through the standard HA UI
(Settings → Add-ons), configurable without SSH, and easy to iterate on
via a normal git-based update flow instead of ad-hoc `docker build`/`docker
run` over SSH.

**Background:** this fallback path exists because the home network's
primary VPN egress (an AmneziaWG tunnel from the Keenetic router to a VPS
at `it-garage`) could in principle be blocked by the ISP one day (plain
WireGuard has already shown to be more fragile than obfuscated
AmneziaWG in practice — see the home router's own incident history).
VLESS+Reality is far harder for DPI to fingerprint. The full mechanism —
Keenetic router → (new) native WireGuard tunnel → Home Assistant →
sing-box TUN → VLESS+Reality → the VPS — was built from scratch and
manually debugged to a fully working state in the session that preceded
this design (see that session's history for the two real bugs found:
missing `ip.global` on the router's WireGuard interface, and Docker's
default `FORWARD DROP` policy silently eating traffic between two
non-Docker interfaces on the host, fixed via `DOCKER-USER` accept
rules). This add-on packages that already-proven mechanism; it does not
change the mechanism itself.

## Scope

**In scope:** the Home Assistant OS side only — the add-on that runs
the WireGuard server + sing-box TUN client + the associated
forwarding/routing setup on the HA host.

**Out of scope:** the Keenetic router side (creating the `Wireguard2`
interface, setting `ip.global`, and flipping the `dns-proxy route`
domain-list entry between the primary tunnel and this fallback) stays a
manual, separate step done via the router's RCI API or web UI, as it is
today. The add-on never holds router admin credentials.

## Repository layout

A new, separate git repository (not part of the `support-bot` project),
structured as a standard Home Assistant add-on repository so it can be
added to Supervisor as a store source:

```
HA_VLESS/
  repository.yaml            # HA add-on repository manifest
  reality-gateway/
    config.yaml               # add-on manifest: options schema, privileges, host_network
    Dockerfile
    rootfs/
      etc/
        cont-init.d/
          10-setup.sh          # one-shot: keys, wg0, wait-for-tun, forwarding rules
        services.d/
          singbox/
            run                 # long-running: exec sing-box
    README.md
    CHANGELOG.md
  docs/
    superpowers/
      specs/                    # design docs for this project (this file)
```

## Add-on internals

**One long-running process, not two.** WireGuard needs no persistent
userspace process once configured — `wg setconf` + `ip link set up`
leaves the tunnel live in the kernel. The only process that needs to
stay running in the foreground is `sing-box run`. So the add-on has:

- `cont-init.d/10-setup.sh` (runs once per container start, s6-overlay's
  init hook, must exit 0 before the long-running service starts):
  1. If `/data/wg-keys.env` doesn't exist yet: generate a server
     keypair, a router-side keypair, and a PSK (`wg genkey`/`wg pubkey`/
     `wg genpsk`), save them to `/data` (persists across restarts and
     add-on updates), and print the router-side values (router private
     key, router's derived public key, PSK, suggested `AllowedIPs`) to
     the add-on log clearly labeled for one-time manual entry into the
     Keenetic router.
  2. Render `wg0`'s config from `/data/wg-keys.env` + the add-on's own
     options (listen port, server/peer addresses), then
     `ip link add wg0 type wireguard`, `wg setconf`, `ip addr add`,
     `ip link set wg0 up`.
  3. Render `/etc/sing-box/config.json` from the add-on's VLESS/Reality
     options.
  4. Wait (poll, capped retries) for `tun-reality` to exist — it's
     created asynchronously by sing-box itself once it starts, so this
     step actually runs *after* step 5 starts sing-box, or step 5 backgrounds
     sing-box and this step polls before returning. (Exact ordering
     detail for the implementation plan — see Open questions.)
  5. Once `tun-reality` exists: idempotently (check-before-add, so
     repeated container restarts don't duplicate rules) set
     `net.ipv4.ip_forward=1`, add the `iptables -t mangle -A PREROUTING
     -i wg0 -j MARK --set-mark 100` rule, `ip rule add fwmark 100 table
     100`, `ip route replace default dev tun-reality table 100`, and —
     the fix found in the preceding debugging session — `iptables -I
     DOCKER-USER -i wg0 -o tun-reality -j ACCEPT` and the reverse
     direction. Without this last pair, Docker's own default `FORWARD
     DROP` policy silently drops all traffic between these two
     non-Docker interfaces.
- `services.d/singbox/run`: `exec sing-box run -c /etc/sing-box/config.json`
  under s6 supervision (auto-restarts sing-box if it crashes; does not
  redo the `cont-init.d` setup).

**Privileges (config.yaml):** `host_network: true`, `privileged:
[NET_ADMIN]`, `devices: ["/dev/net/tun"]`. Needed for `ip link`/`wg`/
`iptables` to affect the real host network namespace, and for the tun
device.

## Configuration (add-on options)

Exposed as normal HA add-on options (editable in Settings → Add-ons →
this add-on → Configuration, no rebuild needed — the add-on re-reads
options via `bashio::config` on each `cont-init.d` run, i.e. on
add-on restart):

```yaml
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
```

Defaults match the already-working, hand-verified values from the
manual build (see the VPS infra project's own notes for the
`amnezia-xray` server these point at). Changing the VLESS fields (e.g.
to point at a different exit server) or the WireGuard subnet is a plain
options edit + add-on restart, no image rebuild.

Note: `vless_uuid` defaults to the ad-hoc test client (`wg-dpi-test`)
created on the VPS's Xray server during manual debugging, alongside two
pre-existing clients. This is fine functionally (Xray doesn't care how
many clients share a server), but conflates "manual test client" and
"this add-on's own identity." If that distinction ever matters (e.g.
wanting to revoke test access without affecting the add-on), mint a
dedicated UUID on the VPS the same way (`docker exec amnezia-xray xray
uuid`, add to `server.json`, `docker restart amnezia-xray`) and update
this option. Not done as part of this design since it has no functional
effect either way.

WireGuard key material is **not** an option field — it's generated once
by the add-on itself (see `cont-init.d` step 1) and persisted in
`/data`, which survives add-on updates/restarts (only wiped by an
explicit uninstall). This means the add-on's identity (its WG keypair,
and the router-side keypair it generates *for* the router) stays stable
across ordinary updates.

## Update / iteration workflow

1. Edit code in this repo (locally, or push from wherever it's cloned).
2. Bump `version` in `reality-gateway/config.yaml`.
3. `git commit` + `git push`.
4. In the HA UI: Settings → Add-ons → Add-on Store → this add-on shows
   an update available → click Update. Supervisor re-pulls the repo and
   rebuilds the image (fully local Docker build on the HA host itself —
   no external registry involved beyond the base image sing-box ships
   from).

The router-added add-on repository is a plain git URL — no GitHub
account requirement beyond hosting the repo somewhere Supervisor can
`git clone` from (a public GitHub repo is the simplest choice, and is
what this design assumes, but any git remote reachable from the HA
host's network would work).

## Non-goals / explicitly deferred

- No router-side automation (see Scope).
- No add-on icon/logo, no translations file, no HACS-style extras — a
  minimal, functional add-on for a single-user setup.
- No support for multiple simultaneous VLESS exit servers or
  active/standby failover logic inside the add-on itself — it runs one
  configured path. If a second exit server is ever wanted, that's a
  separate add-on instance or a follow-up design.

## Open questions for the implementation plan

- Exact `cont-init.d` sequencing between starting sing-box (needed to
  create `tun-reality`) and the s6 "one-shot init must finish before
  the long-running service starts" model — since sing-box itself *is*
  the long-running service. Likely resolved by starting sing-box
  in the background from within `cont-init.d` itself (not via a
  separate `services.d` entry) once the config is rendered, waiting for
  `tun-reality`, doing the routing/forwarding setup, and then `exec`ing
  into `sing-box run` as the container's foreground process at the end
  of the init script (or keeping the backgrounded sing-box and having
  `cont-init.d` just exit 0 while it keeps running as a orphaned but
  supervised... — needs the actual s6-overlay/HA base-image
  conventions checked against the current HA base image version during
  implementation, since getting this wrong means sing-box either
  doesn't restart on crash or `tun-reality` setup races the interface's
  actual appearance).
- Whether `wg_peer_allowed_ip`/`wg_server_address` need IPv6 handling
  (out of scope for v1 unless it turns out to matter).

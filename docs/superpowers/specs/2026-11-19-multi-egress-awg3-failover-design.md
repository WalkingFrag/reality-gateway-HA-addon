# Reality Gateway: multiple AWG3 exits with VLESS failover

Date: 2026-11-19. Status: approved by user; no runtime changes yet.

## Intent

The Keenetic sends all selected IPv4 traffic through its existing
WireGuard connection to Home Assistant. The Reality Gateway add-on chooses a
working exit from two or more AmneziaWG 3.1 (AWG3) servers and the existing
VLESS+Reality server. The choice is automatic, visible in the add-on log, and
never sends selected traffic through the ordinary Home Assistant WAN when no
exit works.

## Approaches

1. Keep AWG on the Keenetic and automate the router's route selection. This
   leaves the add-on unable to select the primary exit and requires router
   credentials/control. It does not meet the chosen ownership model.
2. Send all selected traffic to the add-on and switch its policy-route table
   among dedicated AWG3 interfaces and the current sing-box TUN interface.
   Chosen: the add-on already owns the ingress `wg0`, mark 100, and table 100.
3. Put every exit inside sing-box and use its selector. Its existing VLESS
   outbound fits, but native AWG3 3.1 support is not established here. A
   separate AWG3 userspace implementation avoids relying on that assumption.

## Data path and ownership

```text
selected LAN client -> Keenetic Wireguard2 -> HA wg0 (10.20.30.1)
                                           -> mark 100 / table 100
                                           -> one selected exit:
                                              awg1, awg2, ... -> AWG3 VPS
                                              tun-reality -> VLESS VPS
```

- The Keenetic keeps the current WireGuard peer and sends the entire desired
  IPv4 domain/device policy to that peer. Switching among exits does not edit
  the router. Its old direct AWG route remains a separate router
  configuration, outside the add-on's selection. The Keenetic must disable or
  block IPv6 for this selected policy so it cannot bypass the HA gateway;
  router-side IPv6 settings are verified before cutover.
- `wg0` remains a kernel WireGuard server managed by the add-on. Existing
  keys in `/data/wg-keys.env`, port and peer addresses survive migration.
- Each AWG3 client is a separate userspace `amneziawg-go` interface, configured
  with matching `amneziawg-tools`. Start the userspace process explicitly;
  do not load a kernel module or let `awg-quick` install a host default route.
  The add-on already has host networking, `NET_ADMIN`, and `/dev/net/tun`.
- sing-box and its `tun-reality` interface remain the VLESS exit. The VLESS
  settings already stored in the add-on options remain valid.
- One routing controller is the sole writer of table 100. Remove the existing
  routing service's unconditional 60-second replacement of the VLESS route.
  Candidate-specific tables and marks let probes use each exit independently
  while the production route points to another exit.
- For AWG3 egress, masquerade forwarded `wg0` traffic to that AWG interface's
  client address, accept forwarding in both directions, and clamp TCP MSS to
  the actual tunnel path. Apply equivalent forwarding safeguards to VLESS.
  Do not alter the host's ordinary default route. AWG3 outer UDP sockets and
  the VLESS outer TCP connection use the host's ordinary WAN route.

## Configuration

- Configure exits in the add-on's Home Assistant Configuration tab as a nested
  list. Each AWG3 entry includes its name, priority, endpoint, tunnel address,
  peer public key, client private key, preshared key, and AWG 3.1 parameters.
  The private and preshared keys use password fields. Reject duplicate IDs,
  incomplete configs, and overlapping tunnel addresses before changing routes.
- Keep existing VLESS fields in Supervisor options. The exit list can refer to
  the existing VLESS exit by ID without repeating its credentials. No private
  AWG3 keys, UUIDs, short IDs, or complete AWG3 client configs enter the
  repository or the add-on log. Preserve the current one-time WireGuard router-key log on a
  fresh install so existing onboarding continues to work; it is not repeated
  after the keys are saved in `/data`.
- If the exit list is absent, retain the current VLESS-only behavior. This
  provides a migration path for existing installations. Initial configured
  preference is AWG3 exits in ascending priority, then VLESS; the user can
  reorder them in the add-on configuration.
- Exact option and file format will be validated against Supervisor's current
  app configuration rules during implementation. The Home Assistant app
  configuration folder is backed up with the app.

## Health and selection

- An interface existing or an AWG handshake is only a preliminary signal.
  A candidate is healthy after real HTTPS requests through that specific
  exit succeed against at least one of two independently hosted,
  configurable probe targets.
  Validate the expected response and TLS certificate. The probe must be
  bound to that candidate's routing table; a response via the HA WAN must
  never count as success.
- Probe each exit every 15 seconds. Mark it down after three consecutive
  failed rounds and up after three successful rounds. Prefer the healthy
  exit with the lowest configured priority. After a failover, hold the new
  exit for at least two minutes before automatic failback. These values are
  initial defaults, not measured performance guarantees.
- Switch only the production table 100 default route using one `ip route
  replace` operation. New connections take the new exit; existing TCP/UDP
  sessions may break because the public source IP changes. Log each health
  transition and route change without logging credentials.
- Table 100 always contains a low-priority blackhole default route, installed
  before the mark/rule is enabled. A healthy selected exit adds a preferred
  default route; switching replaces only that preferred route. If its
  interface vanishes, the blackhole remains in the table and prevents
  policy-rule lookup from falling through to the ordinary WAN. If all exits
  are down, remove the preferred route and report `no healthy egress`.
  Preserve this property during startup, restart, crash, and stop. One
  process owns route updates to avoid competing writers.

## Reliability and rollout

- Supervise each AWG3 userspace process and sing-box separately. A failed
  process only removes its own candidate from selection; it must not bring
  down the inbound WireGuard peer. The controller rechecks interfaces and
  rules after process restarts.
- Reconcile existing `wg0`, iptables, and policy rules idempotently on start.
  On orderly stop, remove only rules and interfaces created by this add-on;
  leave a fail-closed route in place until the ingress `wg0` is down. A
  restart or downgrade must not leave two route controllers fighting.
- First verify VLESS-only compatibility on the actual HAOS/aarch64 host.
  Add one AWG3 server, verify forwarded client traffic, then add the other.
  Test loss of each server, recovery, total outage, add-on restart, and
  MTU-sized transfers. Preserve a working previous add-on image/config and
  the existing router route as a rollback path.
- AWG3 server provisioning and client configuration are prerequisites; this
  project does not create remote VPS services. A 3.1 client config must match
  the server's 3.1 parameters. The builder will verify upstream Go/tools
  versions and build support for each advertised architecture before release.
- The two supplied native AWG 3.1 configs identify two client peers on the
  same endpoint. They do not provide server redundancy. Provision a separate
  HA client on each distinct server and enter its values in the add-on options.
  Do not store share links or client configs in the repository.

## Explicit limits

- This is failover, not load balancing. One exit serves new traffic at a time.
- The add-on cannot repair a failed Keenetic-to-HA WireGuard tunnel or a failed
  HA host. It does not automatically change router DNS policies.
- Host networking and policy routing make this a privileged HA app. No extra
  standalone Docker containers or HAOS kernel modules are required.
- IPv6 egress and failover are out of scope for this release, as chosen by the
  user. The current ingress, tunnel addresses, NAT, and policy routing are
  IPv4-only. Selected IPv6 traffic must be blocked or disabled on the
  Keenetic; the add-on cannot enforce a router-side IPv6 policy by itself.

## References

- Current implementation: `reality-gateway/rootfs/etc/cont-init.d/10-setup.sh`
  and `reality-gateway/rootfs/etc/services.d/routing/run`.
- AWG3.1 protocol and client: https://docs.amnezia.org/documentation/amnezia-wg/
  and https://docs.amnezia.org/documentation/instructions/install-amneziawg-go/
- HA app configuration folders: https://contributors.home-assistant.io/apps/guides/options/
- Official self-hosted AWG native export: https://docs.amnezia.org/documentation/instructions/use-amneziawg-app/

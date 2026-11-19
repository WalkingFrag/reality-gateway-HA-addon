# AWG3 Multi-Egress Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Reality Gateway select a healthy AWG3 or VLESS exit for IPv4 traffic forwarded from the Keenetic's existing WireGuard tunnel.

**Architecture:** Keep `wg0` and the sing-box VLESS TUN. Start one userspace AmneziaWG 3.1 interface per configured server, and have one controller probe each exit and own policy-routing table 100. An always-present blackhole route prevents traffic from falling through to the HA WAN.

**Tech Stack:** Home Assistant app with S6, Bashio, Python 3 standard library, iproute2/iptables, sing-box, pinned upstream `amneziawg-go` and `amneziawg-tools`.

**Spec:** `docs/superpowers/specs/2026-11-19-multi-egress-awg3-failover-design.md`

## Global Constraints

- Existing WireGuard keys in `/data/wg-keys.env`, `wg0` peer settings, and existing VLESS options survive an upgrade.
- No AWG3 exit list means the current VLESS-only behavior and first-run router key handoff remain usable.
- AWG3 private keys and VLESS secrets never enter git or logs; validate all option values before changing routes.
- The supplied AWG 3.1 configs are two peers on one endpoint. Provision a separate HA client on each distinct server; enter server and peer fields in the add-on Configuration tab, not files in the repository.
- The release routes selected IPv4 traffic only. The Keenetic must disable or block selected IPv6 traffic before cutover.
- No host default route changes, HAOS kernel modules, standalone containers, or router credentials.
- The production route is table 100 with mark 100. A less preferred blackhole route must remain after a selected interface disappears.
- Fixed priorities, not load balancing: probe every 15 seconds, three failed or successful rounds for state change, two-minute minimum hold before failback.
- One probe round succeeds when at least one of two independently hosted configured HTTPS targets responds as expected through that specific exit.
- New sessions may move after failover; established sessions may disconnect when the public IP changes.

## Review Focus

- Invalid or incomplete AWG option values must be rejected before any shell/network action (Task 1 test).
- Deleting a selected TUN interface must leave table 100's blackhole and never route marked traffic via the main table (Task 3 test).
- Probe success over the HA WAN must not mark an exit healthy (Task 4 test).
- Failed AWG process startup must leave VLESS eligible and the inbound `wg0` running (Task 5 test).
- Flapping probe results must not bounce the selected route or bypass the two-minute failback hold (Task 5 test).

## File map

- `reality-gateway/Dockerfile`: install Python and build pinned AWG userspace binaries per advertised architecture.
- `reality-gateway/config.yaml`: add nested AWG3 exit options with password fields for secrets, keep old VLESS options, bump version only for a tested release.
- `reality-gateway/rootfs/etc/cont-init.d/10-setup.sh`: preserve WG and sing-box setup, move policy-route ownership out of the legacy service.
- `reality-gateway/rootfs/etc/services.d/routing/run`: replace the unconditional VLESS route loop with the controller entrypoint.
- `reality-gateway/rootfs/usr/local/lib/reality_gateway/config.py`: parse and validate exit and probe configuration.
- `reality-gateway/rootfs/usr/local/lib/reality_gateway/awg.py`: explicitly start/configure/monitor AWG3 userspace interfaces.
- `reality-gateway/rootfs/usr/local/lib/reality_gateway/net.py`: reconcile host route, mark, NAT, forwarding, MSS, and cleanup rules.
- `reality-gateway/rootfs/usr/local/lib/reality_gateway/probe.py`: make a certificate-checked HTTPS request through a specifically marked exit.
- `reality-gateway/rootfs/usr/local/lib/reality_gateway/controller.py`: health state, priority choice, restart reconciliation, and logs.
- `tests/`: focused unit tests with a command/socket fake, plus a network-namespace integration harness for marked forwarded packets.
- `reality-gateway/README.md` and `CHANGELOG.md`: configuration, migration, testing, and rollback instructions.

---

### Task 1: Configuration and migration

**Files:** Create `config.py`, `tests/test_config.py`; modify `reality-gateway/config.yaml` for nested exit options.

**Interfaces:** `load_config(options_path: Path) -> GatewayConfig`; `GatewayConfig.exits` is an ordered tuple of `ExitSpec(id, kind, priority, awg_settings)` and `GatewayConfig.probes` is a tuple of `ProbeTarget(host, ip, path, expected_status)`. Absent exit list yields one VLESS exit and `legacy_mode=True`.

- [ ] Write tests for absent exit list, two AWG3 exits plus VLESS, duplicate IDs/priorities, fewer than two probe targets, malformed IPs, missing keys, and malformed endpoint. Add `rootfs/usr/local/lib` to the test import path.
- [ ] Run `python -m unittest discover -s tests -p 'test_config.py' -v`; confirm the new tests fail.
- [ ] Implement strict Supervisor option parsing and AWG settings validation. Require unique tunnel addresses and safe interface names derived from IDs.
- [ ] Rerun the focused tests and confirm pass; commit Task 1.

### Task 2: Pinned AWG3 binaries and process lifecycle

**Files:** Modify `Dockerfile`; create `awg.py`, `tests/test_awg.py`.

**Interfaces:** `AwgManager.start(exit: ExitSpec) -> str` returns the interface name; `AwgManager.is_running(exit_id: str) -> bool`; `AwgManager.stop(exit_id: str) -> None`. Commands run through an injectable runner. The manager explicitly launches `amneziawg-go -f <interface>`, configures it with `awg setconf`, then adds the configured IPv4 address and sets MTU/link up. No `awg-quick` auto route.

- [ ] Pin `amneziawg-go` tag `v3.1.20260828` (`b5928efb6ca19f0153958460c3d141f04abc5c2e`) and `amneziawg-tools` tag `v3.1.20260812` (`ee0f0a9aa34ff0a0da4b3433b9512781cfe02843`); verify versions and image builds for every architecture still advertised in `config.yaml` (at least the live `aarch64` target). If an architecture cannot build, resolve that before changing advertised support.
- [ ] Write lifecycle tests for successful setup, process startup failure, config failure cleanup, duplicate restart, and stop without affecting `wg0`.
- [ ] Run `python -m unittest discover -s tests -p 'test_awg.py' -v`; confirm failure, implement the process manager, then rerun for pass.
- [ ] Run image build and `amneziawg-go --version` / `awg --version` in the image; commit Task 2.

### Task 3: Fail-closed host routing and AWG NAT

**Files:** Create `net.py`, `tests/test_net.py`; modify `rootfs/etc/services.d/routing/run` and the setup script only as needed for single ownership.

**Interfaces:** `NetworkManager.reconcile(exits: tuple[ExitSpec, ...]) -> None`; `NetworkManager.select(interface: str | None) -> None`; `NetworkManager.cleanup() -> None`. `select(None)` removes only the preferred default; the low-priority blackhole remains. Every command is idempotent and is executed by the injectable runner.

- [ ] Write tests that inspect command order: blackhole before mark/rule, preferred route alongside blackhole, interface disappearance, all-down, restart with preexisting rules, AWG masquerade, DOCKER-USER both directions, MSS clamp, and orderly stop (`blackhole`, then `wg0` down, then removal of mark/rule).
- [ ] Run `python -m unittest discover -s tests -p 'test_net.py' -v`; confirm failure.
- [ ] Implement route/rule/iptables reconciliation. Use a unique comment or exact match for owned iptables rules and avoid deleting unrelated host rules. Preserve the legacy VLESS-only route when no multi-egress config exists.
- [ ] Rerun tests; then exercise marked packets and interface removal in a disposable Linux network namespace, verifying `ip route get` cannot fall through to the main WAN route. Commit Task 3.

### Task 4: Exit-bound HTTPS probes

**Files:** Create `probe.py`, `tests/test_probe.py`.

**Interfaces:** `probe(exit: ExitSpec, target: ProbeTarget, mark: int, timeout: float) -> bool`. Create a socket to the configured IP, apply `SO_MARK` before connect, wrap with verified TLS using `target.host` as SNI, send `GET target.path` with its Host header, and check `expected_status`. No implicit DNS or direct retry.

- [ ] Write tests for successful response, bad certificate, wrong status, timeout, and `SO_MARK` failure; assert socket marking happens before connect and no unmarked retry occurs. A controller round succeeds if either of the two targets succeeds.
- [ ] Run `python -m unittest discover -s tests -p 'test_probe.py' -v`; confirm failure; implement; rerun for pass.
- [ ] In a disposable network namespace, prove a probe marked for an unavailable candidate fails even when the namespace WAN can reach the test endpoint. Commit Task 4.

### Task 5: Health controller and supervised startup

**Files:** Create `controller.py`, `tests/test_controller.py`; modify `rootfs/etc/services.d/routing/run`, `rootfs/etc/cont-init.d/10-setup.sh`, and any S6 service files needed.

**Interfaces:** `choose_exit(state: GatewayState, now: float) -> str | None`; `GatewayController.run() -> None`. Probe tables/marks are deterministic and distinct from production mark/table 100. The controller is the only production route writer; sing-box and AWG process liveness are inputs to health state.

- [ ] Write deterministic tests for startup, preferred healthy exit, AWG down/VLESS up, all down, recovery, three-round thresholds, two-minute failback hold, and failed AWG startup with `wg0` still usable.
- [ ] Run `python -m unittest discover -s tests -p 'test_controller.py' -v`; confirm failure.
- [ ] Implement candidate probe tables, health state machine, S6 wiring/restart reconciliation, transition logging, and orderly cleanup. Never log key material or full config.
- [ ] Rerun focused and full unit suites; exercise a fake-process integration run that kills/restarts one exit. Commit Task 5.

### Task 6: End-to-end rollout and documentation

**Files:** Modify `reality-gateway/README.md`, `CHANGELOG.md`, and `config.yaml` version; create `tests/integration/` harness where useful.

**Interfaces:** Example add-on options use placeholders only. Document router IPv6 blocking, probe targets, port/endpoint reachability, key handling, and rollback to the previous add-on.

- [ ] Run the complete unit suite, shell syntax checks, `sing-box check`, and image builds for supported architectures. Test forwarded packets and exit loss in a disposable Linux/HAOS test environment.
- [ ] Document configuration, migration, router IPv6 policy, and rollback. Bump the app version and commit a candidate release after local checks pass.
- [ ] With live rollout authorization, create dedicated HA clients on both VPSs, enter their AWG 3.1 parameters in the add-on Configuration tab, and install the candidate on the HAOS/aarch64 target. Verify the old config still routes via VLESS, then configure one AWG3 server and a second. Confirm actual Keenetic-forwarded traffic exits through each selected VPS and not merely a local curl.
- [ ] Simulate each exit loss and recovery, total outage, add-on restart, and MTU-sized transfers. Confirm table 100 retains the blackhole and no selected IPv4 flow exits via HA WAN. Record the observed result and publish the tested release.

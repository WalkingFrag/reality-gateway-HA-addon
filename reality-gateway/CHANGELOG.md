# Changelog

## 0.1.3

- Fixed: the three required options introduced in 0.1.2 (`vless_server`,
  `vless_uuid`, `vless_reality_short_id`) were omitted from `options:`
  entirely, which is the syntax for a truly *optional* field (paired with
  `str?` in `schema:`), not a required one — the Supervisor Configuration UI
  didn't render fields for them at all. Required-with-no-default in an HA
  add-on means the key stays in `schema:` as plain `str` (no `?`) **and**
  is present in `options:` with value `null`. Fixed to that pattern.

## 0.1.2

- **Security fix:** `vless_server`, `vless_uuid`, and `vless_reality_short_id`
  were shipped as real, working default values in `config.yaml` — the UUID
  and short ID are credentials/anti-probing values, not public data, and
  ended up briefly exposed in this repo's history. They now have no default
  and must be entered manually as required options. The exposed UUID has
  been rotated on the exit server; the leaked values were also scrubbed from
  this repo's git history.

## 0.1.1

- Fixed: `sysctl -w net.ipv4.ip_forward=1` fails under this add-on's actual
  privilege level (`NET_ADMIN` capability, not full `--privileged`), which
  previously aborted the routing service before any policy routing rule was
  applied — the add-on would show as running while zero traffic actually
  flowed. The write is now best-effort with a clear warning if forwarding
  isn't already enabled on the host.
- Fixed: `wg0`'s IP address was only applied the first time the interface
  was created, so changing `wg_server_address` and restarting silently kept
  the old address (since `wg0` lives in the host network namespace and
  survives restarts). The address is now flushed and reapplied on every run.
- Fixed: the router-side WireGuard private key and preshared key were
  re-logged into Home Assistant's persisted logs on every restart/update,
  not just on first generation. Full secret values are now logged only on
  the run that actually generates them.
- Added: a fail-closed `blackhole` default route seeded in the policy
  routing table before/while waiting for the sing-box tunnel, so any window
  without a live tunnel drops WireGuard traffic instead of leaking it out
  the host's normal WAN.
- Added: the rendered sing-box config is now validated with `sing-box check`
  at init time, failing loudly on bad VLESS/Reality option values instead of
  leaving the add-on silently non-functional.
- Minor robustness fix: the `ip rule` idempotency check now captures
  `ip rule show` to a variable before grepping it, avoiding a theoretical
  `pipefail`/SIGPIPE race that could cause a spurious duplicate rule add.
- Fixed the placeholder repository URL and added a documentation link to
  the add-on store listing.

## 0.1.0

- Initial release: WireGuard server + sing-box VLESS+Reality TUN client, packaged as a Home Assistant add-on.

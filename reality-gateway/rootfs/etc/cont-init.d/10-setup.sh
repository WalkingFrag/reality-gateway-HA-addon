#!/command/with-contenv bashio
# reality-gateway cont-init: one-shot setup (runs once per container start)
set -euo pipefail

KEYS_FILE=/data/wg-keys.env

generate_keys_if_needed() {
    if [[ -f "${KEYS_FILE}" ]]; then
        bashio::log.info "WireGuard keys already exist in ${KEYS_FILE}, reusing them"
        return 1
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
    return 0
}

log_router_values() {
    # shellcheck disable=SC1090
    source "${KEYS_FILE}"
    if [[ "$1" == "fresh" ]]; then
        bashio::log.notice "=== Router-side WireGuard values (enter these into the Keenetic Wireguard2 interface) ==="
        bashio::log.notice "Router private key: ${ROUTER_PRIVATE_KEY}"
        bashio::log.notice "Router public key:  ${ROUTER_PUBLIC_KEY}"
        bashio::log.notice "Preshared key:      ${PSK}"
        bashio::log.notice "Peer (this add-on) public key: ${SERVER_PUBLIC_KEY}"
        bashio::log.notice "Suggested AllowedIPs on the router: $(bashio::config 'wg_peer_allowed_ip')"
        bashio::log.notice "=========================================================================="
    else
        bashio::log.info "This add-on's public key: ${SERVER_PUBLIC_KEY} (router-side secrets already provisioned; not re-printed — see /data/wg-keys.env if you need them again)"
    fi
}

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
    fi
    # wg0 lives in the host network namespace (host_network: true) and
    # survives container restarts, so the address must be reapplied
    # idempotently every run — not just on first creation — otherwise
    # changing wg_server_address and restarting silently keeps the old
    # address. Note: `ip addr replace` only replaces an address that has the
    # exact same IP/prefix already assigned; if wg_server_address changed, it
    # just adds the new address alongside the stale one instead of removing
    # it (verified empirically). Flush first so the interface always ends up
    # with exactly the configured address.
    ip addr flush dev wg0
    ip addr add "${server_address}" dev wg0
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
        "utls": {
          "enabled": true,
          "fingerprint": "chrome"
        },
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

    if ! sing-box check -c /etc/sing-box/config.json; then
        bashio::exit.nok "Rendered sing-box config is invalid — check the VLESS/Reality options"
    fi
}

if generate_keys_if_needed; then
    log_router_values fresh
else
    log_router_values reused
fi
setup_wg0
render_singbox_config

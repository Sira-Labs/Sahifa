#!/bin/sh
# Start Caddy (web image, spec 021): refuse a half-configured password gate with a message that
# names the missing variable, instead of Caddy's error about base64.
set -eu
# Caddy uses a placeholder's default ({$SAHIFA_DOMAIN::80}) only for an unset variable; compose
# passes empty ones (SAHIFA_DOMAIN: ${SAHIFA_DOMAIN:-}), which left the site without an address.
for var in SAHIFA_DOMAIN SAHIFA_API_UPSTREAM SAHIFA_EDGE_AUTH; do
  eval "value=\${$var:-}"
  [ -n "$value" ] || unset "$var"
done
case "${SAHIFA_EDGE_AUTH:-off}" in
  off) ;;
  basic)
    for var in SAHIFA_BASIC_AUTH_USER SAHIFA_BASIC_AUTH_HASH; do
      eval "value=\${$var:-}"
      if [ -z "$value" ]; then
        echo "sahifa-web: SAHIFA_EDGE_AUTH=basic needs $var (hash: caddy hash-password)" >&2
        exit 2
      fi
    done
    ;;
  *)
    echo "sahifa-web: SAHIFA_EDGE_AUTH must be off or basic, not ${SAHIFA_EDGE_AUTH}" >&2
    exit 2
    ;;
esac
# Read the config once first: `caddy run` exits on a bad one without saying why.
caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile

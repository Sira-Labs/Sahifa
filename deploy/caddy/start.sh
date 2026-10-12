#!/bin/sh
# Start Caddy (web image, spec 021): refuse a half-configured password gate with a message that
# names the missing variable, instead of Caddy's error about base64.
set -eu
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
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile

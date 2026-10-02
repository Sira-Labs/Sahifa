#!/bin/sh
# One image, two roles, chosen by SAHIFA_ROLE (default api):
#   api     migrate to the newest schema (idempotent, safe on every start), then serve.
#   worker  arrives with spec 007 (Procrastinate); refused until then.
# A failed migration stops the new api container before uvicorn starts, so the previous
# release keeps serving. `sahifa-api healthcheck` is the image's HEALTHCHECK.
set -eu
role="${SAHIFA_ROLE:-api}"
if [ "${1:-}" = "healthcheck" ]; then
  [ "$role" = worker ] && exit 0
  exec python -c 'import sys, urllib.request
try:
    sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2).status == 200 else 1)
except OSError:
    sys.exit(1)'
fi
case "$role" in
  api)
    python -m sahifa.db.migrate upgrade head
    exec uvicorn sahifa.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"
    ;;
  *)
    echo "SAHIFA_ROLE must be api (the worker arrives with spec 007), not '$role'" >&2
    exit 2
    ;;
esac

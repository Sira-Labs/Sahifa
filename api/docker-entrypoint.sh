#!/bin/sh
# One image, two roles, chosen by SAHIFA_ROLE (default api):
#   api     migrate to the newest schema (idempotent, safe on every start), then serve.
#   worker  the Procrastinate worker (spec 008): needs SAHIFA_SCAN_EXECUTION=queue (exit 2
#           otherwise), waits up to 5 minutes for the api to migrate (exit 3 after that) and
#           never migrates itself.
# A failed migration stops the new api container before uvicorn starts, so the previous
# release keeps serving. `sahifa-api healthcheck` is the image's HEALTHCHECK: /healthz for the
# api, a running `python -m sahifa.worker` process for the worker, which serves no HTTP.
set -eu
role="${SAHIFA_ROLE:-api}"
if [ "${1:-}" = "healthcheck" ]; then
  if [ "$role" = worker ]; then
    # [s] keeps grep from matching its own command line.
    for f in /proc/[0-9]*/cmdline; do
      if tr '\0' ' ' < "$f" 2>/dev/null | grep -q -- '-m [s]ahifa\.worker'; then exit 0; fi
    done
    exit 1
  fi
  exec python -c 'import sys, urllib.request
try:
    sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2).status == 200 else 1)
except OSError:
    sys.exit(1)'
fi
case "$role" in
  api)
    python -m sahifa.db.migrate upgrade head
    # X-Forwarded-For is trusted from private networks only (the web container, CapRover's
    # nginx), so a client reaching the api directly cannot pick its own address (spec 012).
    exec uvicorn sahifa.main:app --host 0.0.0.0 --port 8000 --proxy-headers \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7}"
    ;;
  worker)
    exec python -m sahifa.worker
    ;;
  *)
    echo "SAHIFA_ROLE must be api or worker, not '$role'" >&2
    exit 2
    ;;
esac

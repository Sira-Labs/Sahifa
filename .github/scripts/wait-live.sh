#!/usr/bin/env bash
# Wait until a deployment serves the wanted commit (release.yml and promote.yml).
#
# CapRover accepts a deploy before it pulls the image, so a failed pull or a container that
# never starts would otherwise leave the job green. Polls <URL>/version.json (web image) and
# <URL>/api/version (api image) and, with CHECK_WORKER=true, waits until <URL>/healthz lists a
# connected worker on the commit in its `workers` field (the worker names its database
# connections `sahifa-worker/<commit>`; spec 008). The workflows set CHECK_WORKER only when
# the environment has CAPROVER_APP_TOKEN_WORKER, i.e. a worker app exists.
#
#   URL=https://sahifa-stg.siralabs.org WANT=<full sha> CHECK_WORKER=true wait-live.sh
# A deploy without a URL to check fails: set CAPROVER_WEB_URL on the environment.
# BASIC_AUTH (user:password) is sent when set: until sign-in arrives in R2 (ADR-0010) the web
# app sits behind CapRover's HTTP basic auth, which also covers these endpoints.
# TIMEOUT (seconds, default 600; 0 = look once) and INTERVAL (15).
set -euo pipefail

if [ -z "${URL:-}" ]; then
  echo "::error::CAPROVER_WEB_URL is not set on this environment: cannot confirm that the deploy went live"
  exit 1
fi
URL="${URL%/}"
: "${WANT:?WANT (the commit to wait for) is required}"
auth=()
if [ -n "${BASIC_AUTH:-}" ]; then auth=(-u "$BASIC_AUTH"); fi
deadline=$((SECONDS + ${TIMEOUT:-600}))
while :; do
  web=$(curl -fsS -m 10 "${auth[@]}" "$URL/version.json" 2>/dev/null | jq -r '.commit // empty' 2>/dev/null || true)
  api=$(curl -fsS -m 10 "${auth[@]}" "$URL/api/version" 2>/dev/null | jq -r '.commit // empty' 2>/dev/null || true)
  worker_ok=true
  workers=""
  if [ "${CHECK_WORKER:-false}" = "true" ]; then
    # /healthz answers 503 while a dependency is down, so its body is read without -f.
    # Each entry is a commit, a connection name `sahifa-worker/<commit>` or an object with `commit`.
    workers=$(curl -sS -m 10 "${auth[@]}" "$URL/healthz" 2>/dev/null \
      | jq -r '[(.workers // [])[] | if type == "object" then (.commit // "") else tostring end | sub("^sahifa-worker/"; "")] | join(",")' 2>/dev/null || true)
    if [[ ",$workers," != *",$WANT,"* ]]; then worker_ok=false; fi
  fi
  if [ "$web" = "$WANT" ] && [ "$api" = "$WANT" ] && [ "$worker_ok" = "true" ]; then
    if [ "${CHECK_WORKER:-false}" = "true" ]; then echo "web, api and worker run $WANT"; else echo "web and api run $WANT"; fi
    exit 0
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    waited=$(( ${TIMEOUT:-600} / 60 ))
    if [ "${CHECK_WORKER:-false}" = "true" ]; then
      echo "::error::after ${waited} minutes $URL serves web '${web:-?}', api '${api:-?}', workers '${workers:-none}', not $WANT; see the apps' deployment logs in CapRover"
    else
      echo "::error::after ${waited} minutes $URL serves web '${web:-?}', api '${api:-?}', not $WANT; see the apps' deployment logs in CapRover (a 401 means BASIC_AUTH is missing or wrong)"
    fi
    exit 1
  fi
  sleep "${INTERVAL:-15}"
done

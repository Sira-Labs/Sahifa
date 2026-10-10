#!/usr/bin/env bash
# Check that the web image runs Caddy without root and still serves (CI job `web-image`,
# spec 019).
#
#   web-image-check.sh <image> <commit it was built from>
#
# 1. The image's configured user is 10001:10001.
# 2. Plain HTTP on :80: every process runs as uid 10001; /version.json answers 200 with the
#    commit and the CSP of spec 012; Caddy may write /data but not /srv.
# 3. The compose upgrade: a caddy_data volume left behind by a root Caddy is handed to 10001 by
#    the bundle's own `web-volume` service, then Caddy binds :443 with SAHIFA_DOMAIN=localhost
#    and writes its local certificates to that volume.
#
# Runs from the repository root; needs docker with compose, curl and python3.
set -euo pipefail

image=${1:?usage: web-image-check.sh <image> <commit>}
commit=${2:?usage: web-image-check.sh <image> <commit>}
project="sahifa-check-$$"
http="$project-http"
https="$project-https"
work=$(mktemp -d)

compose() {
  SAHIFA_WEB_IMAGE="$image" SAHIFA_TAG=unused POSTGRES_PASSWORD=unused \
    docker compose -p "$project" -f deploy/compose.yaml "$@"
}

cleanup() {
  local status=$?
  if ((status != 0)); then
    for c in "$http" "$https"; do
      docker logs "$c" 2>&1 | tail -n 40 | sed "s/^/[$c] /" >&2 || true
    done
  fi
  docker rm -f "$http" "$https" >/dev/null 2>&1 || true
  compose down -v >/dev/null 2>&1 || true
  rm -rf "$work"
  [[ $made_env == yes ]] && rm -f deploy/.env
  exit "$status"
}
made_env=no
trap cleanup EXIT

fail() {
  echo "web-image: FAIL, $*" >&2
  exit 1
}

# Wait until <url> answers (curl options before it), at most 60 s.
wait_for() {
  for _ in $(seq 60); do
    curl -fsS -o /dev/null "$@" 2>/dev/null && return 0
    sleep 1
  done
  fail "no answer from ${*: -1}"
}

# Every process of container <name> runs as uid 10001.
all_10001() {
  local uids
  # docker top needs the pid column to match processes to the container.
  uids=$(docker top "$1" -eo pid,uid | awk 'NR > 1 { print $2 }')
  [[ -n $uids ]] || fail "$1 has no processes"
  if grep -vqx 10001 <<<"$uids"; then
    docker top "$1" -eo pid,uid,args >&2
    fail "$1 runs a process as another user than 10001"
  fi
}

user=$(docker image inspect -f '{{.Config.User}}' "$image")
[[ $user == 10001:10001 ]] || fail "the image's user is '$user', want 10001:10001"
echo "web-image: configured user 10001:10001"

# The API upstream is a closed port: only the static part is checked.
docker run -d --name "$http" -p 127.0.0.1:18080:80 -e SAHIFA_API_UPSTREAM=127.0.0.1:9 "$image" >/dev/null
wait_for http://127.0.0.1:18080/version.json
all_10001 "$http"
echo "web-image: every process runs as uid 10001"

status=$(curl -sS -D "$work/headers" -o "$work/version.json" -w '%{http_code}' http://127.0.0.1:18080/version.json)
[[ $status == 200 ]] || fail "/version.json answered $status"
grep -qi "^content-security-policy: default-src 'self'" "$work/headers" || fail "/version.json has no CSP"
grep -qi '^x-content-type-options: nosniff' "$work/headers" || fail "/version.json has no nosniff"
served=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["commit"])' "$work/version.json")
[[ $served == "$commit" ]] || fail "/version.json names $served, want $commit"
echo "web-image: /version.json 200 with the security headers and the commit"

docker exec "$http" sh -c 'touch /data/probe && rm /data/probe' || fail "Caddy cannot write /data"
if docker exec "$http" sh -c 'touch /srv/probe' 2>/dev/null; then
  fail "Caddy can write /srv"
fi
if docker exec "$http" sh -c 'echo >> /etc/caddy/Caddyfile' 2>/dev/null; then
  fail "Caddy can write its Caddyfile"
fi
echo "web-image: /data writable, /srv and the Caddyfile not"

# The compose bundle reads deploy/.env for the api; an empty one is enough to start web-volume.
if [[ ! -e deploy/.env ]]; then
  : > deploy/.env
  made_env=yes
fi
# A volume as a root Caddy left it: certificates owned by root.
compose run --rm --no-deps --user 0:0 --entrypoint sh web-volume \
  -c 'mkdir -p /data/caddy/certificates && touch /data/caddy/certificates/old.crt' >/dev/null
compose run --rm --no-deps web-volume >/dev/null
volume="${project}_caddy_data"
owner=$(docker run --rm --user 0:0 --entrypoint stat -v "$volume:/data" "$image" -c '%u:%g' /data/caddy/certificates/old.crt)
[[ $owner == 10001:10001 ]] || fail "web-volume left the old certificate owned by $owner"
echo "web-image: web-volume hands an old caddy_data volume to 10001"

docker run -d --name "$https" -p 127.0.0.1:18443:443 -e SAHIFA_DOMAIN=localhost \
  -e SAHIFA_API_UPSTREAM=127.0.0.1:9 -v "$volume:/data" "$image" >/dev/null
wait_for -k --resolve localhost:18443:127.0.0.1 https://localhost:18443/version.json
all_10001 "$https"
docker run --rm --user 0:0 --entrypoint sh -v "$volume:/data" "$image" \
  -c 'test -n "$(find /data/caddy/pki -user 10001 -name root.crt)"' || fail "no local CA written by 10001"
echo "web-image: :443 bound by uid 10001, certificates written to the volume"

#!/usr/bin/env bash
# Follow deploy/quickstart.md on a fresh machine (CI job `quickstart`, spec 021).
#
#   quickstart-check.sh <api image> <web image>
#
# Downloads nothing: it copies the files the quick start downloads from this checkout, fills
# .env the way the quick start says, mounts the faulty shop's files read-only, adds a Postgres
# source with a read-only and a writing login, starts the bundle behind the password gate and
# runs check_api.py against it.
set -euo pipefail

api_image=${1:?usage: quickstart-check.sh <api image> <web image>}
web_image=${2:?usage: quickstart-check.sh <api image> <web image>}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
work=$(mktemp -d)
cd "$work"

# Step 1: the three files of the quick start.
cp "$repo/deploy/compose.yaml" compose.yaml
cp "$repo/deploy/.env.example" .env
cp "$repo/deploy/compose.override.example.yaml" compose.override.yaml
compose=(docker compose -p sahifa-quickstart -f compose.yaml -f compose.override.yaml -f "$here/quickstart/source.yaml")

cleanup() {
  local status=$?
  if ((status != 0)); then
    "${compose[@]}" logs --no-color --tail 80 api worker web source >&2 || true
  fi
  "${compose[@]}" down -v >/dev/null 2>&1 || true
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

# Set KEY=value in .env: replace the line when it is there, else append it.
setenv() {
  python3 - "$1" "$2" <<'PY'
import re, sys
key, value = sys.argv[1], sys.argv[2]
text = open(".env").read()
line = f"{key}={value}"
# The variable's own line first, else a commented example of it, else a new line.
for pattern in (rf"^{re.escape(key)}=.*$", rf"^# ?{re.escape(key)}=\S*$"):
    text, n = re.subn(pattern, lambda m: line, text, count=1, flags=re.M)
    if n:
        break
open(".env", "w").write(text if n else text.rstrip("\n") + f"\n{line}\n")
PY
}

password=$(openssl rand -hex 12)
owner_password=$(openssl rand -hex 16)
reader_password=$(openssl rand -hex 16)
writer_password=$(openssl rand -hex 16)
hash=$(docker run --rm --entrypoint caddy "$web_image" hash-password --plaintext "$password")

# Step 2: the password at the edge. Step 3: the sources.
setenv SAHIFA_API_IMAGE "$api_image"
setenv SAHIFA_WEB_IMAGE "$web_image"
setenv POSTGRES_PASSWORD "$(openssl rand -hex 24)"
setenv SAHIFA_AUTH_MODE proxy
setenv SAHIFA_ACCESS_GATE basic-auth-at-proxy
setenv SAHIFA_EDGE_AUTH basic
setenv SAHIFA_BASIC_AUTH_USER me
setenv SAHIFA_BASIC_AUTH_HASH "'$hash'"
setenv SAHIFA_CONN_READER "postgresql://sahifa_reader:$reader_password@source:5432/shop?schemas=public"
setenv SAHIFA_CONN_WRITER "postgresql://writer:$writer_password@source:5432/shop?schemas=public"
setenv SAHIFA_CONN_EXPORTS /sources/exports
setenv SOURCE_OWNER_PASSWORD "$owner_password"

# The folder the quick start mounts read-only, with the faulty shop in it.
mkdir exports
chmod 777 exports
"${compose[@]}" run --rm --no-deps --user 0:0 -v "$work/exports:/out" api python -m sahifa_core.cli synth /out --rows 2000 >/dev/null
chmod -R a+rX exports

# The source database: the shop, a read-only login and a writing one.
"${compose[@]}" up -d --wait source
"${compose[@]}" run --rm --no-deps -v "$here/quickstart/load_shop.py:/tmp/load_shop.py:ro" api \
  python /tmp/load_shop.py /sources/exports "postgresql://owner:$owner_password@source:5432/shop"
"${compose[@]}" exec -T source psql -q -U owner -d shop -v ON_ERROR_STOP=1 \
  -v reader_password="$reader_password" -v writer_password="$writer_password" < "$here/quickstart/grants.sql"

# Step 4: start.
"${compose[@]}" up -d
for _ in $(seq 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -u "me:$password" http://localhost/api/version || true)
  [[ $code == 200 ]] && break
  sleep 2
done
[[ $code == 200 ]] || { echo "quickstart: FAIL, the bundle did not answer through the gate ($code)" >&2; exit 1; }
echo "quickstart: the bundle answers through the gate"

# Step 5: test the logins and scan.
python3 "$here/quickstart/check_api.py" http://localhost me "$password"

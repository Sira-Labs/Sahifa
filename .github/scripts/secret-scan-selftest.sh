#!/usr/bin/env bash
# Prove that the secret scan catches what it should (CI job `secrets`, spec 019).
#
# Commits a GitHub-token-shaped value, generated here at run time so that no such value is ever
# in this repository, to a throw-away git repository and asserts that gitleaks reports it under
# the `github-pat` rule. Then asserts that a repository with only a clean commit passes.
#
#   secret-scan-selftest.sh <path to gitleaks>
set -euo pipefail

gitleaks=${1:?usage: secret-scan-selftest.sh <path to gitleaks>}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# The default rules only: a config in the environment must not change what is tested.
unset GITLEAKS_CONFIG GITLEAKS_CONFIG_TOML

# A fresh repository with one commit of <content> in config.txt.
repo() {
  local dir="$work/$1" content=$2
  git init -q "$dir"
  git -C "$dir" config user.name selftest
  git -C "$dir" config user.email selftest@example.invalid
  git -C "$dir" config commit.gpgsign false
  printf '%s\n' "$content" > "$dir/config.txt"
  git -C "$dir" add config.txt
  git -C "$dir" commit -q -m "add config"
}

# The rule IDs gitleaks reports for <dir>, one per line; exit status 0 (clean) or 1 (leaks).
scan() {
  local dir=$1 report="$work/$(basename "$1").json" status=0
  "$gitleaks" git --no-banner --redact --log-level error -f json -r "$report" "$dir" || status=$?
  python3 -c 'import json, sys; [print(f["RuleID"]) for f in json.load(open(sys.argv[1]))]' "$report"
  return "$status"
}

token="ghp_$(openssl rand -hex 18)"
repo leak "GITHUB_TOKEN=$token"
if rules=$(scan "$work/leak"); then
  echo "selftest: FAIL, the scan passed a commit with a GitHub token" >&2
  exit 1
fi
if ! grep -qx github-pat <<<"$rules"; then
  echo "selftest: FAIL, expected the github-pat rule, got: ${rules:-nothing}" >&2
  exit 1
fi
echo "selftest: a committed token is found (github-pat)"

repo clean "SAHIFA_CONN_SHOP is set in the environment, never here"
if ! rules=$(scan "$work/clean"); then
  echo "selftest: FAIL, the scan reported a clean commit: $rules" >&2
  exit 1
fi
echo "selftest: a clean commit passes"

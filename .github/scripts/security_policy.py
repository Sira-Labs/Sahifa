#!/usr/bin/env python3
"""Dependency policy checks for CI (spec 012, ADR-0008, ADR-0015). Standard library only.

  licences python   the installed distributions of the current environment (a runtime-only
                    `uv sync`), skipping the project's own packages
  licences pnpm     `pnpm licenses list --prod --json` on stdin
  audit pip         `pip-audit -f json` on stdin
  audit pnpm        `pnpm audit --json` on stdin (high and critical only)

Licences must be on `allowed` in the policy, or the package listed under `exceptions` with its
licence and a reason. Vulnerabilities fail unless listed in the ignore file with a reason and
an expiry date; an expired entry fails too. Exit code 1 on any failure, 2 on unusable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any

# Classifier and free-text spellings of the licences we meet, as SPDX ids.
ALIASES: dict[str, str] = {
    "mit": "MIT",
    "mit license": "MIT",
    "mit-0": "MIT-0",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "isc": "ISC",
    "isc license (iscl)": "ISC",
    "psf-2.0": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "mpl-2.0": "MPL-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "0bsd": "0BSD",
    "unlicense": "Unlicense",
    "the unlicense (unlicense)": "Unlicense",
    "ofl-1.1": "OFL-1.1",
    "lgpl-3.0": "LGPL-3.0-only",
    "lgpl-3.0-only": "LGPL-3.0-only",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
    "gpl-3.0": "GPL-3.0-only",
    "gnu general public license v3 (gplv3)": "GPL-3.0-only",
    "agpl-3.0": "AGPL-3.0-only",
}
CLASSIFIER = "License :: OSI Approved :: "


def spdx(name: str) -> str:
    """One licence name as an SPDX id where we know it, else as given. Parentheses that wrap
    the whole name are dropped; ones inside a name ("... (MPL 2.0)") are part of it."""
    text = name.strip()
    while text.startswith("(") and text.endswith(")") and text.lower() not in ALIASES:
        text = text[1:-1].strip()
    return ALIASES.get(text.lower(), text)


def satisfied(expression: str, allowed: set[str]) -> bool:
    """Whether a licence expression is allowed: any `OR` alternative whose `AND` parts are all
    allowed. Grouping parentheses are dropped, which is exact for the shapes packages publish
    ("(MIT OR Apache-2.0)", "MIT AND PSF-2.0")."""
    if spdx(expression) in allowed:
        return True
    flat = re.sub(r"(^|\s)\(|\)(\s|$)", " ", expression)
    for alternative in re.split(r"\s+OR\s+", flat.strip(), flags=re.IGNORECASE):
        parts = [
            spdx(p) for p in re.split(r"\s+AND\s+", alternative.strip(), flags=re.IGNORECASE) if p.strip()
        ]
        if parts and all(p in allowed for p in parts):
            return True
    return False


@dataclass
class Policy:
    allowed: set[str]
    # package name (normalised) -> (licence expression it is allowed under, reason)
    exceptions: dict[str, tuple[str, str]]
    skip: set[str]


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_policy(path: Path) -> Policy:
    data = tomllib.loads(path.read_text())
    exceptions = {}
    for e in data.get("exceptions", []):
        if not e.get("reason"):
            raise SystemExit(f"{path}: exception for {e.get('package')} has no reason")
        exceptions[normalise(e["package"])] = (e["licence"], e["reason"])
    return Policy(
        allowed=set(data["allowed"]),
        exceptions=exceptions,
        skip={normalise(s) for s in data.get("skip", [])},
    )


def distribution_licence(dist: metadata.Distribution) -> str:
    """The licence of an installed distribution: PEP 639's `License-Expression`, else its
    licence classifiers (several are alternatives), else a short `License` field; `UNKNOWN` if
    none. Classifiers come before the free text, which is often "Dual License" or a full text."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c[len(CLASSIFIER) :] for c in meta.get_all("Classifier") or [] if c.startswith(CLASSIFIER)]
    if classifiers:
        return " OR ".join(spdx(c) for c in classifiers)
    free = (meta.get("License") or "").strip()
    if free and "\n" not in free and len(free) <= 80 and free.upper() != "UNKNOWN":
        return free
    return "UNKNOWN"


def check(packages: dict[str, str], policy: Policy) -> list[str]:
    """Failures, one line each, for packages (name -> licence) outside the policy."""
    failures = []
    for name, licence in sorted(packages.items()):
        key = normalise(name)
        if key in policy.skip:
            continue
        if key in policy.exceptions:
            allowed_as, _reason = policy.exceptions[key]
            if spdx(licence) != spdx(allowed_as) and licence != allowed_as:
                failures.append(f"{name}: {licence} (excepted only as {allowed_as})")
            continue
        if not satisfied(licence, policy.allowed):
            failures.append(f"{name}: {licence}")
    return failures


def python_packages() -> dict[str, str]:
    return {
        d.metadata["Name"]: distribution_licence(d) for d in metadata.distributions() if d.metadata["Name"]
    }


def pnpm_packages(listing: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {p["name"]: licence for licence, pkgs in listing.items() for p in pkgs}


@dataclass
class Ignore:
    id: str
    reason: str
    expires: date


def load_ignores(path: Path) -> tuple[list[Ignore], list[str]]:
    """The accepted vulnerabilities, and failures for entries that are expired or incomplete."""
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    entries, failures = [], []
    for e in data.get("ignore", []):
        if not e.get("id") or not e.get("reason") or not e.get("expires"):
            failures.append(f"{path}: entry {e} needs id, reason and expires")
            continue
        expires = e["expires"] if isinstance(e["expires"], date) else date.fromisoformat(str(e["expires"]))
        if expires < date.today():
            failures.append(f"{path}: ignore of {e['id']} expired on {expires}")
        entries.append(Ignore(e["id"], e["reason"], expires))
    return entries, failures


def pip_findings(report: dict[str, Any]) -> list[tuple[str, set[str]]]:
    """(description, ids including aliases) for each vulnerability in a pip-audit report."""
    out = []
    for dep in report.get("dependencies", []):
        for v in dep.get("vulns", []):
            ids = {v["id"], *v.get("aliases", [])}
            out.append((f"{dep['name']} {dep.get('version', '')}: {v['id']}", ids))
    return out


def pnpm_findings(report: dict[str, Any]) -> list[tuple[str, set[str]]]:
    """(description, ids) for each high or critical advisory in a `pnpm audit --json` report."""
    out = []
    for adv in (report.get("advisories") or {}).values():
        if adv.get("severity") not in ("high", "critical"):
            continue
        ids = {str(adv.get("id")), *(adv.get("cves") or [])}
        if adv.get("github_advisory_id"):
            ids.add(adv["github_advisory_id"])
        name = adv.get("github_advisory_id") or adv.get("id")
        out.append((f"{adv.get('module_name')}: {name} ({adv['severity']})", ids))
    return out


def read_json(stream: Any) -> Any:
    try:
        return json.load(stream)
    except json.JSONDecodeError as e:
        raise SystemExit(2) from e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--policy", type=Path, default=Path("security/licences.toml"))
    parser.add_argument("--ignores", type=Path, default=Path("security/audit-ignore.toml"))
    parser.add_argument("kind", choices=["licences", "audit"])
    parser.add_argument("source", choices=["python", "pnpm", "pip"])
    args = parser.parse_args(argv)

    if args.kind == "licences":
        policy = load_policy(args.policy)
        if args.source == "python":
            packages = python_packages()
        elif args.source == "pnpm":
            packages = pnpm_packages(read_json(sys.stdin))
        else:
            parser.error("licences takes python or pnpm")
        failures = check(packages, policy)
        label = f"{len(packages)} {args.source} packages"
    else:
        if args.source == "python":
            parser.error("audit takes pip or pnpm")
        report = read_json(sys.stdin)
        findings = pip_findings(report) if args.source == "pip" else pnpm_findings(report)
        ignores, failures = load_ignores(args.ignores)
        accepted = {i.id for i in ignores}
        failures += [text for text, ids in findings if not ids & accepted]
        label = f"{len(findings)} {args.source} findings, {len(ignores)} accepted"

    for line in failures:
        sys.stdout.write(f"FAIL {line}\n")
    sys.stdout.write(f"{args.kind} {args.source}: {label}, {len(failures)} failing\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

"""Assert what the quick start promises, through the password gate (CI job `quickstart`,
spec 021).

    python3 check_api.py <base URL> <user> <password>

1. Without the password, /api/version answers 401.
2. The connections reader, writer and exports test as read_only, can_write and read_only.
3. Scans of the reader and of the folder succeed with findings; a scan with the writer login
   stores can_write in its report.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE, USER, PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()


def call(method: str, path: str, body: Any = None, auth: bool = True) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "X-Sahifa-Request": "1"}
    if auth:
        headers["Authorization"] = AUTH
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            text = r.read().decode()
            return r.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def check(condition: bool, message: str) -> None:
    if not condition:
        print(f"quickstart: FAIL, {message}", file=sys.stderr)
        sys.exit(1)
    print(f"quickstart: {message}")


status, _ = call("GET", "/api/version", auth=False)
check(status == 401, f"the gate asks for a password ({status})")

status, listed = call("GET", "/api/connections")
check(status == 200, f"connections listed through the gate ({status})")
ids = {c["name"]: c["id"] for c in listed["items"]}
check({"reader", "writer", "exports"} <= set(ids), f"connections registered from .env: {sorted(ids)}")

expected = {"reader": "read_only", "writer": "can_write", "exports": "read_only"}
for name, verdict in expected.items():
    status, tested = call("POST", f"/api/connections/{ids[name]}/test")
    if not isinstance(tested, dict):
        check(False, f"{name}: test answered {status} {tested}")
    got = tested.get("access") or {}
    check(
        status == 200 and tested["ok"] and got.get("verdict") == verdict,
        f"{name}: test sees {tested.get('assets')} assets, {got.get('verdict')}",
    )

scans = {}
for name in expected:
    status, scan = call("POST", "/api/scans", {"connection_id": ids[name], "sample_rows": 0})
    check(status == 202, f"{name}: scan started ({status})")
    scans[name] = scan["id"]

deadline = time.monotonic() + 600
for name, sid in scans.items():
    while True:
        _, scan = call("GET", f"/api/scans/{sid}")
        if scan["status"] in ("succeeded", "failed") or time.monotonic() > deadline:
            break
        time.sleep(3)
    check(scan["status"] == "succeeded", f"{name}: scan {scan['status']} {scan.get('error') or ''}".strip())
    _, report = call("GET", f"/api/scans/{sid}/report")
    access = (report.get("source_access") or {}).get("verdict")
    check(access == expected[name], f"{name}: report says {access}")
    if name != "writer":
        check(len(report["findings"]) > 0, f"{name}: {len(report['findings'])} findings in the faulty shop")

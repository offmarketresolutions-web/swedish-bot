"""Post-deploy smoke test: hits the 3 load-bearing routes against a running
server (stdlib only, no new deps). Exits 1 on any non-2xx/3xx response.

    uv run python tools/smoke.py                       # http://localhost:8000
    SMOKE_BASE_URL=https://nordland.3dpresence.com uv run python tools/smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")

CHECKS = [
    ("GET", "/", None),
    ("GET", "/demo/homepage", None),
    ("POST", "/api/chat/session", {}),
]


def main() -> int:
    failed = False
    for method, path, body in CHECKS:
        url = BASE_URL.rstrip("/") + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except urllib.error.URLError as e:
            print(f"FAIL  {method} {path} -> connection error: {e}")
            failed = True
            continue
        ok = 200 <= status < 400
        print(f"{'PASS' if ok else 'FAIL'}  {method} {path} -> {status}")
        failed = failed or not ok
    if failed:
        print("smoke FAILED")
        return 1
    print("smoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

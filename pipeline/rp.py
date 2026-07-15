#!/usr/bin/env python3
"""rp.py — minimal RunPod CLI helper (stdlib only). Audit finding A2: the
generation pipeline referenced an uncommitted scratchpad helper; this is the
committed replacement. Key comes from RUNPOD_API_KEY — never hardcode it.

  python3 pipeline/rp.py run <endpoint_id> <payload.json>
  python3 pipeline/rp.py status <endpoint_id> <job_id>
  python3 pipeline/rp.py cancel <endpoint_id> <job_id>
  python3 pipeline/rp.py patch_endpoint <endpoint_id> '{"workersMax":2}'

Output: a one-line label, then the JSON response (callers parse line 2+).
"""
import json
import os
import sys
import urllib.request

KEY = os.environ.get("RUNPOD_API_KEY")
if not KEY:
    sys.exit("set RUNPOD_API_KEY")
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def req(url, data=None, method=None, timeout=120):
    rq = urllib.request.Request(url, data=data, method=method, headers=H)
    return json.loads(urllib.request.urlopen(rq, timeout=timeout).read())


def main():
    cmd, ep = sys.argv[1], sys.argv[2]
    if cmd == "run":
        payload = open(sys.argv[3], "rb").read()
        out = req(f"https://api.runpod.ai/v2/{ep}/run", payload)
    elif cmd == "status":
        out = req(f"https://api.runpod.ai/v2/{ep}/status/{sys.argv[3]}")
    elif cmd == "cancel":
        out = req(f"https://api.runpod.ai/v2/{ep}/cancel/{sys.argv[3]}", b"", "POST")
    elif cmd == "patch_endpoint":
        out = req(f"https://rest.runpod.io/v1/endpoints/{ep}",
                  sys.argv[3].encode(), "PATCH")
    else:
        sys.exit(f"unknown command {cmd}")
    print(cmd)
    print(json.dumps(out))


if __name__ == "__main__":
    main()

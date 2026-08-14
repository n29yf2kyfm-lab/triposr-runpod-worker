#!/usr/bin/env python3
"""pod_state.py — print a RunPod pod's state WITH ITS ENV REDACTED.

Why this exists (council audit 2026-08-14): a raw `GET /v1/pods/<id>` response
was piped through json.tool into the session transcript, and the pod's env —
which carries SB_KEY and HF_TOKEN — went with it. Transcripts persist across
rollbacks on this machine and have been harvested for credentials before
(that is HOW lost Sketchfab tokens were recovered, per CLAUDE.md), so a key
printed once is a key exposed. The owner had to be told to rotate two keys.

Never dump a pod JSON raw again. Use this: it prints the fields that matter
for diagnosis — desiredStatus, uptime, GPU util, cost, image, dockerStartCmd —
and replaces every env VALUE with its name only.

Usage:
    RUNPOD_API_KEY=... python3 pipeline/qc/pod_state.py <pod_id>
    (or source /root/.alam3d_env first)
"""
import json
import os
import sys
import urllib.request


def pod_state(pod_id, api_key=None):
    key = api_key or os.environ.get("RUNPOD_API_KEY")
    if not key:
        raise SystemExit("RUNPOD_API_KEY not set — source /root/.alam3d_env")
    req = urllib.request.Request(
        f"https://rest.runpod.io/v1/pods/{pod_id}",
        headers={"Authorization": f"Bearer {key}"})
    d = json.load(urllib.request.urlopen(req))
    rt = d.get("runtime") or {}
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "desiredStatus": d.get("desiredStatus"),
        "uptimeSeconds": rt.get("uptimeInSeconds"),
        "gpuUtilPercent": [g.get("gpuUtilPercent") for g in rt.get("gpus", [])],
        "costPerHr": d.get("costPerHr"),
        "image": d.get("imageName"),
        "dockerStartCmd": d.get("dockerStartCmd"),
        "lastStartedAt": d.get("lastStartedAt"),
        # names only — the values are the whole reason this file exists
        "env_NAMES_ONLY": sorted((d.get("env") or {}).keys()),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(pod_state(sys.argv[1]), indent=1))

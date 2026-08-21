#!/usr/bin/env python3
"""supervise.py — what every agent is ACTUALLY doing, from artefacts on disk.

WHY THIS SHAPE, and it is the whole point. The obvious design is a watcher that
asks each agent to report every N minutes. This project has already paid for
that design twice:

  * "background processes in this container do not survive session idle" — the
    night watch DIED AT ITS FIRST TICK and a pod then billed unwatched for
    7h10m ($3.15), which was later reconstructed to the penny.
  * "six subagents were spawned overnight; ZERO returned reports."

and the council audit's rule: "Never claim protection from a watchdog that has
not been observed to fire once."

An agent cannot be compelled to report on a cadence — a message reaches it at
its next tool round, whenever that is. But an agent that is working WRITES: log
lines, receipts, GLBs, CHECKPOINT.md. So this reads the filesystem, the pod
list and the balance, and infers state from evidence. Nothing here depends on
an agent cooperating, and nothing here is a background process that can die
without saying so.

WHAT "STALE" MEANS HERE. No file written in the directory for STALE_MIN
minutes. That is not proof an agent is dead — it may be mid-thought, or waiting
on a pod — so it is reported as a flag for a human, never as a verdict. Same
rule this project applies to every other candidate finder.

Run:  python3 pipeline/machine/supervise.py [--stale-min 5] [--json]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

SCRATCH = os.environ.get(
    "SUPERVISE_ROOT",
    "/tmp/claude-0/-home-user-triposr-runpod-worker/"
    "34795087-6986-5aae-b59f-cce8aae2f506/scratchpad")
REPO = "/home/user/triposr-runpod-worker"
# Directories that are agent workspaces rather than one-off scratch. Anything
# else in the scratchpad is ignored so the report stays readable.
WATCH = ["sharptest", "direct3d", "compressed", "oemdata", "blendercost",
         "worldwide", "mergeverify", "build", "final", "cabin", "glass",
         "rear2", "mobile", "skin", "merge"]


def newest(path):
    """(mtime, name, count) of the most recently written file, recursively."""
    best, name, n = 0.0, None, 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            n += 1
            try:
                m = os.path.getmtime(os.path.join(root, f))
            except OSError:
                continue
            if m > best:
                best, name = m, os.path.relpath(os.path.join(root, f), path)
    return best, name, n


def tail(path, k=2):
    try:
        with open(path, "r", errors="replace") as fh:
            return [l.rstrip() for l in fh.readlines()[-k:] if l.strip()]
    except OSError:
        return []


def load_env(path="/root/.alam3d_env"):
    """Load credentials OURSELVES rather than trusting the caller to source them.

    This project has the scar: a relaunch that forgot to source the env file
    died one line in, and the failure was indistinguishable from a healthy start
    — it logged its manifest count and exited, and was reported as running.
    wave_render.py:load_env exists for the same reason. On this tool's very
    first run the balance printed "?" for exactly this, which would have hidden
    a low-balance condition — and billing exhaustion here looks identical to GPU
    capacity starvation."""
    if os.environ.get("RUNPOD_API_KEY"):
        return
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except OSError:
        pass


def runpod():
    """Pods and balance. A pod at 0% GPU with climbing uptime is the restart
    loop; a rented pod with runtime null still BILLS."""
    load_env()
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        return {"error": "RUNPOD_API_KEY not readable from env or /root/.alam3d_env"}
    out = {}
    try:
        req = urllib.request.Request(
            "https://rest.runpod.io/v1/pods",
            headers={"Authorization": f"Bearer {key}"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        pods = d if isinstance(d, list) else d.get("data", [])
        out["pods"] = [{
            "id": p.get("id"),
            "name": (p.get("name") or "")[:24],
            "desired": p.get("desiredStatus"),
            # POLL PROGRESS, NOT DESIRE: desiredStatus reads RUNNING straight
            # through an infinite restart loop. Uptime resetting while the wall
            # clock climbs IS that loop.
            "uptime_s": (p.get("runtime") or {}).get("uptimeInSeconds"),
            "gpu_pct": [g.get("gpuUtilPercent")
                        for g in ((p.get("runtime") or {}).get("gpus") or [])],
        } for p in pods]
    except Exception as e:
        out["pods_error"] = f"{type(e).__name__}: {e}"
    try:
        req = urllib.request.Request(
            "https://api.runpod.io/graphql",
            data=json.dumps({"query": "query { myself { clientBalance "
                                      "currentSpendPerHr } }"}).encode(),
            # A User-Agent is REQUIRED here. RunPod's GraphQL endpoint sits
            # behind Cloudflare, which 403s python-urllib's default UA while
            # returning 200 to curl — CLAUDE.md records this, and it cost ~40
            # minutes once when a flat balance was misdiagnosed as GPU capacity
            # starvation. Without it this tool prints "balance ?" forever and
            # silently hides the one condition it most needs to surface:
            # billing exhaustion looks EXACTLY like capacity starvation.
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "User-Agent": "expertcarcheck-supervise/1.0"})
        out["billing"] = json.load(
            urllib.request.urlopen(req, timeout=30))["data"]["myself"]
    except Exception as e:
        out["billing_error"] = f"{type(e).__name__}: {e}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-min", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    now = time.time()

    rows = []
    for d in WATCH:
        p = os.path.join(SCRATCH, d)
        if not os.path.isdir(p):
            continue
        mt, nm, n = newest(p)
        age = (now - mt) / 60 if mt else None
        cp = os.path.join(p, "CHECKPOINT.md")
        rows.append({
            "dir": d, "files": n,
            "age_min": round(age, 1) if age is not None else None,
            "newest": nm,
            "stale": (age is not None and age > a.stale_min),
            "checkpoint": tail(cp, 2) if os.path.exists(cp) else [],
        })
    rows.sort(key=lambda r: (r["age_min"] is None, r["age_min"] or 0))

    # Live local compute. NEVER pgrep -f a pattern the harness wrapper could
    # contain — a wait loop then matches itself and never exits, and a pkill on
    # a broad pattern has killed this session's own shell three times. `ps` and
    # a substring filter is a read, not a match-and-act.
    procs = []
    try:
        ps = subprocess.run(["ps", "-eo", "pid,etime,pcpu,args"],
                            capture_output=True, text=True, timeout=20).stdout
        for line in ps.splitlines()[1:]:
            if ("blender" in line or "python3" in line) and "supervise.py" not in line:
                procs.append(line.strip()[:120])
    except Exception as e:
        procs = [f"ps failed: {type(e).__name__}"]

    git = {}
    try:
        git["head"] = subprocess.run(
            ["git", "-C", REPO, "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        git["dirty"] = len([l for l in subprocess.run(
            ["git", "-C", REPO, "status", "--porcelain"],
            capture_output=True, text=True, timeout=20).stdout.splitlines()])
    except Exception as e:
        git["error"] = f"{type(e).__name__}: {e}"

    try:
        st = os.statvfs("/")
        free_gb = round(st.f_bavail * st.f_frsize / 1e9, 1)
    except Exception:
        free_gb = None

    rp = runpod()
    report = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "agents": rows,
              "procs": procs[:6], "git": git, "free_gb": free_gb, "runpod": rp}

    if a.json:
        print(json.dumps(report, indent=1))
        return

    print(f"=== SUPERVISE {report['ts']} ===")
    for r in rows:
        flag = "STALE" if r["stale"] else "ok   "
        age = f"{r['age_min']:6.1f}m" if r["age_min"] is not None else "     -"
        print(f"  [{flag}] {r['dir']:<12} {r['files']:>4} files  last {age}  {r['newest'] or ''}")
        for l in r["checkpoint"]:
            print(f"            | {l[:96]}")
    print(f"  -- local compute: {len(procs)} proc(s)")
    for l in procs[:4]:
        print(f"     {l}")
    pods = rp.get("pods", [])
    print(f"  -- runpod: {len(pods)} pod(s)  balance "
          f"{rp.get('billing', {}).get('clientBalance', '?')}")
    for p in pods:
        # A pod whose uptime RESETS while the wall clock climbs is restart-looping;
        # GPU at 0% means nothing is computing. Both are printed so a human sees it.
        print(f"     {p['id']} {p['name']} desired={p['desired']} "
              f"uptime={p['uptime_s']}s gpu={p['gpu_pct']}")
    print(f"  -- git: {git.get('head','?')}  dirty={git.get('dirty','?')}  "
          f"free={free_gb}GB")
    stale = [r["dir"] for r in rows if r["stale"]]
    print(f"  -- STALE (>{a.stale_min}m, a flag for a human, not a verdict): "
          f"{stale or 'none'}")


if __name__ == "__main__":
    sys.exit(main())

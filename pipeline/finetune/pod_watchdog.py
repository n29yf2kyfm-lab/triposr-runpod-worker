#!/usr/bin/env python3
"""pod_watchdog.py — delete a training pod on any terminal state.

Why this lives in the repo rather than a temp directory: the sandbox scratchpad
and home directory were both wiped repeatedly on 2026-07-27, and every wipe
killed the supervisor that was supposed to shut the pod down. A pod left running
on `sleep infinity` bills at ~$1.40/hr until a human notices. Anything that
guards money belongs in version control.

It only watches and deletes — it never launches anything.

Usage:  RUNPOD_API_KEY=... python3 pipeline/finetune/pod_watchdog.py <pod_id>
"""
import os
import subprocess
import sys
import time
import urllib.request

POLL_SECONDS = 60
MAX_HOURS = 24


def fetch(url, timeout=30):
    # curl, not urllib: the sandbox egress proxy 403s urllib for *.proxy.runpod.net
    r = subprocess.run(["curl", "-s", "-m", str(timeout), url],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def delete(pod, key, why):
    for attempt in range(5):
        req = urllib.request.Request(f"https://rest.runpod.io/v1/pods/{pod}",
                                     method="DELETE",
                                     headers={"Authorization": "Bearer " + key})
        try:
            urllib.request.urlopen(req, timeout=60).read()
            print(f"POD {pod} DELETED ({why})", flush=True)
            return True
        except Exception as e:
            print(f"delete attempt {attempt+1} failed: {str(e)[:70]}", flush=True)
            time.sleep(10 * (attempt + 1))
    print(f"POD_DELETE_FAILED {pod} — DELETE IT MANUALLY, IT IS STILL BILLING", flush=True)
    return False


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: pod_watchdog.py <pod_id>")
    pod = sys.argv[1]
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("RUNPOD_API_KEY missing from env")
    # Say up front whether evidence archiving is armed — a watchdog launched
    # without SB_KEY silently skips the Supabase archive and nobody knows
    # until the evidence is needed.
    print("log archiving:", "ARMED" if os.environ.get("SB_KEY") else
          "DISARMED (no SB_KEY in env - captures print locally only)", flush=True)
    url = f"https://{pod}-8000.proxy.runpod.net"

    last = ""
    for _ in range(int(MAX_HOURS * 3600 / POLL_SECONDS)):
        status = fetch(url + "/status.json")
        if status and status != last:
            print(f"{time.strftime('%H:%M:%S')} {status.strip()}", flush=True)
            last = status
        if "DONE" in status or "FATAL" in status:
            # CAPTURE THE LOG BEFORE THE DELETE. On 2026-07-28 this watchdog
            # deleted a FATAL pod 47 seconds after the failure — faster than
            # anyone could read the traceback — and the only copy of the
            # diagnosis died with it. A watchdog that destroys the evidence
            # of the failure it is reacting to guards money by spending it
            # again on the retry.
            tail = fetch(url + "/stage_b.log", timeout=90)[-12000:]
            if not tail:
                time.sleep(5)   # one retry: a race with the proxy is cheaper than lost evidence
                tail = fetch(url + "/stage_b.log", timeout=90)[-12000:]
            if tail:
                print("---- last 12000 bytes of pod log ----", flush=True)
                print(tail, flush=True)
                print("---- end of pod log ----", flush=True)
                sb = os.environ.get("SB_KEY")
                if sb:
                    try:
                        rq = urllib.request.Request(
                            "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/"
                            f"car-meshes/audit/pod_logs/{pod}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log",
                            data=tail.encode(), method="POST")
                        for h, v in (("apikey", sb), ("Authorization", "Bearer " + sb),
                                     ("Content-Type", "text/plain"), ("x-upsert", "true")):
                            rq.add_header(h, v)
                        urllib.request.urlopen(rq, timeout=120).read()
                        print("log tail archived to car-meshes/audit/pod_logs/", flush=True)
                    except Exception as e:
                        print(f"log archive failed (kept locally above): {str(e)[:70]}", flush=True)
            else:
                print("WARNING: could not fetch the pod log before deletion", flush=True)
            delete(pod, key, "DONE" if "DONE" in status else "FATAL")
            return
        time.sleep(POLL_SECONDS)
    print("watchdog budget exhausted; pod deliberately left running", flush=True)


if __name__ == "__main__":
    main()

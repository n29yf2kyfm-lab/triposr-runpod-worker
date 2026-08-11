"""Staged progress for the damage worker.

Copied in pattern from the building worker, including the expensive default it
learned: pushing progress through the RunPod SDK left jobs stuck IN_PROGRESS
on the live endpoint, so SDK progress is OFF unless a deployment turns it back
on after confirming its workers finalise. stderr logging is always on and has
never let anyone down.

A photo inspection is faster than a building scan but still multi-second once
a VLM is in the loop, and the app should show the analysis moving — fetching,
analysing, scoring, pricing, mapping to 3D, rendering the report.
"""
import os
import sys

try:
    import runpod
except ImportError:  # tests and local runs
    runpod = None

SDK_PROGRESS = os.environ.get("DAMAGE_SDK_PROGRESS", "0") == "1"

STAGE_PLANS = {
    "inspect": ["fetching", "analysing", "scoring", "pricing",
                "mapping_3d", "reporting"],
    "compare": ["fetching", "analysing", "diffing", "reporting"],
    "report":  ["scoring", "pricing", "reporting"],
}


class Progress:
    """Emits stage updates for one job; degrades to stderr when the SDK is
    absent (tests) or disabled (default)."""

    def __init__(self, job, mode):
        self.job = job
        self.mode = mode
        self.stages = STAGE_PLANS.get(mode, [])
        self.index = 0
        self.emitted = []

    def stage(self, name, **extra):
        if name in self.stages:
            self.index = self.stages.index(name) + 1
        payload = {"stage": name, "step": self.index,
                   "steps": len(self.stages) or None, "mode": self.mode}
        payload.update(extra)
        self.emitted.append(payload)
        self._publish(payload)
        return payload

    def note(self, message, **extra):
        payload = {"stage": "note", "message": message, "mode": self.mode}
        payload.update(extra)
        self.emitted.append(payload)
        self._publish(payload)
        return payload

    def _publish(self, payload):
        print(f"[progress] {payload}", file=sys.stderr)
        if runpod is None or not SDK_PROGRESS:
            return
        try:
            runpod.serverless.progress_update(self.job, payload)
        except Exception:
            pass

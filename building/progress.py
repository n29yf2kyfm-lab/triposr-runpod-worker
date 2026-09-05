"""Staged progress reporting.

A vehicle generation takes tens of seconds. A building scan takes minutes:
fetch the capture, estimate poses, densify, scale, register, segment, export.
Without staged updates the app shows a spinner for four minutes and the user
assumes it has hung.

The vehicle worker proved the pattern — it publishes the intermediate image
the moment it exists so the app can display it while the slow 3D stage runs.
Same idea, more stages.
"""
import os
import sys

try:
    import runpod
except ImportError:  # tests and local runs
    runpod = None


# Whether to push progress through the RunPod SDK as well as to the log.
#
# OFF by default, and that default was bought expensively. On the live
# endpoint every job that called runpod.serverless.progress_update() reached
# its final stage and then never finalised — the job sat IN_PROGRESS until it
# was cancelled, across every mode, including one that makes no network calls
# at all. The single job that ever returned cleanly was one rejected by
# validation, which returns BEFORE this class is constructed and so never
# calls the SDK. A malformed-input job on the same warm worker answers in
# 224ms; identical work with progress updates ran past seven minutes.
#
# Live progress is a nice-to-have. A job that never returns is fatal, so the
# optional thing is what gets degraded. Set BUILDING_SDK_PROGRESS=1 to turn
# it back on once a worker is confirmed to finalise jobs with it enabled.
SDK_PROGRESS = os.environ.get("BUILDING_SDK_PROGRESS", "0") == "1"

# Ordered stages per mode, so the client can render a real progress bar
# instead of an indeterminate spinner.
# Each plan must list the stages the module ACTUALLY emits, in order.
#
# Four of these listed stages that no module ever reaches — reconstruct's
# "meshing", structure's "fitting_planes", services' "connecting" and
# "building_ifc". The effect is the opposite of the one intended two lines
# above: a client rendering a real progress bar sees it jump 1 -> 2 -> 4 and
# finish at 5 of 5 having skipped a step, which reads as a stalled job.
# Aspirational stages belong in PLAN.md, not in a progress plan.
STAGE_PLANS = {
    "reconstruct": ["fetching", "poses", "densifying", "scaling",
                    "exporting"],
    "structure":   ["fetching", "segmenting", "building_ifc", "exporting"],
    "services":    ["fetching", "extracting_runs", "classifying",
                    "exporting"],
    "planning":    ["fetching", "screening", "exporting"],
    "model":       ["reading", "building", "exporting"],
    "register":    ["fetching", "coarse_align", "icp", "scoring",
                    "exporting"],
    "roof":        ["fetching", "clipping_footprint", "fitting_planes",
                    "extracting_edges", "quantities", "exporting"],
    "price":       ["fetching", "quantities", "pricing", "exporting"],
    "supply":      ["fetching", "matching_products", "quoting", "exporting"],
    "valuation":   ["fetching", "comparables", "indexing", "valuing",
                    "exporting"],
    "drawing":     ["fetching", "reading", "scaling", "measuring",
                    "exporting"],
    "condition":   ["fetching", "detecting", "locating_3d", "grading",
                    "costing", "exporting"],
    "design":      ["fetching", "massing", "compliance_check", "exporting"],
    "render":      ["aerial", "rendering", "delivering"],
    "scan":        ["fetching", "verifying", "orienting", "delivering"],
    "propose":     ["locating", "footprint", "orientation",
                    "clearances", "roof", "designing", "checking",
                    "exporting", "rendering", "photoreal"],
}


class Progress:
    """Emits stage updates for one job. Safe to use when the runpod SDK is
    absent (tests) — it degrades to stderr logging."""

    def __init__(self, job, mode):
        self.job = job
        self.mode = mode
        self.stages = STAGE_PLANS.get(mode, [])
        self.index = 0
        self.emitted = []

    def stage(self, name, **extra):
        """Advance to a named stage and publish it."""
        if name in self.stages:
            self.index = self.stages.index(name) + 1
        payload = {
            "stage": name,
            "step": self.index,
            "steps": len(self.stages) or None,
            "mode": self.mode,
        }
        payload.update(extra)
        self.emitted.append(payload)
        self._publish(payload)
        return payload

    def note(self, message, **extra):
        """Publish a message without advancing the stage — used for
        findings the app can show live ('142 frames', 'scale from LiDAR')."""
        payload = {"stage": "note", "message": message, "mode": self.mode}
        payload.update(extra)
        self.emitted.append(payload)
        self._publish(payload)
        return payload

    def _publish(self, payload):
        # Always to stderr: it costs nothing, it lands in the worker logs,
        # and it is the only progress reporting that has never let us down.
        print(f"[progress] {payload}", file=sys.stderr)
        if runpod is None or not SDK_PROGRESS:
            return
        try:
            runpod.serverless.progress_update(self.job, payload)
        except Exception:
            # Progress is best-effort. Never let a reporting failure kill a
            # job that is otherwise succeeding.
            pass

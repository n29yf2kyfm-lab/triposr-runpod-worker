"""Staged progress reporting.

A vehicle generation takes tens of seconds. A building scan takes minutes:
fetch the capture, estimate poses, densify, scale, register, segment, export.
Without staged updates the app shows a spinner for four minutes and the user
assumes it has hung.

The vehicle worker proved the pattern — it publishes the intermediate image
the moment it exists so the app can display it while the slow 3D stage runs.
Same idea, more stages.
"""
import sys

try:
    import runpod
except ImportError:  # tests and local runs
    runpod = None


# Ordered stages per mode, so the client can render a real progress bar
# instead of an indeterminate spinner.
STAGE_PLANS = {
    "reconstruct": ["fetching", "poses", "densifying", "scaling",
                    "meshing", "exporting"],
    "structure":   ["fetching", "segmenting", "fitting_planes",
                    "building_ifc", "exporting"],
    "services":    ["fetching", "extracting_runs", "connecting",
                    "classifying", "building_ifc", "exporting"],
    "register":    ["fetching", "coarse_align", "icp", "scoring",
                    "exporting"],
    "price":       ["fetching", "quantities", "pricing", "exporting"],
    "supply":      ["fetching", "matching_products", "quoting", "exporting"],
    "condition":   ["fetching", "detecting", "locating_3d", "grading",
                    "costing", "exporting"],
    "design":      ["fetching", "massing", "compliance_check", "exporting"],
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
        print(f"[progress] {payload}", file=sys.stderr)
        if runpod is None:
            return
        try:
            runpod.serverless.progress_update(self.job, payload)
        except Exception:
            # Progress is best-effort. Never let a reporting failure kill a
            # job that is otherwise succeeding.
            pass

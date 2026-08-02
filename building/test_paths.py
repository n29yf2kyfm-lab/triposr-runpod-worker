"""Tests for output path resolution.

Written after the first live job on the new RunPod endpoint hung in the
exporting stage, on an endpoint created with no network volume while the
image insisted on writing to /runpod-volume. The lesson is narrow and worth
keeping: a mount point existing is not the same as it being writable, and an
env var baked into the image silently defeats any runtime check.

Run: python building/test_paths.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths as P  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


TMP = tempfile.gettempdir()


# ---- 1. is the volume really usable? --------------------------------------
check("1a a writable directory is available", P.volume_available(TMP))
check("1b a missing directory is not",
      not P.volume_available("/definitely/not/here"))
# Existence is NOT the test — a mount point can be present and unbacked.
check("1c a read-only directory is not available",
      not P.volume_available("/proc"), "/proc should not accept a temp file")
check("1d a file is not a directory",
      not P.volume_available(os.path.join(TMP, "any-file-not-a-dir")))


# ---- 2. resolution order ---------------------------------------------------
# An explicit setting always wins, so a deployment that DOES attach a volume
# is never second-guessed.
os.environ["TEST_OUT_DIR"] = "/explicit/volume/path"
check("2a explicit env wins",
      P.resolve("TEST_OUT_DIR", "sub", "local") == "/explicit/volume/path")
del os.environ["TEST_OUT_DIR"]

got = P.resolve("TEST_OUT_UNSET", "building-outputs", "building-outputs",
                root="/definitely/not/here")
check("2b falls back locally when there is no volume",
      got == os.path.join(TMP, "building-outputs"), got)

got = P.resolve("TEST_OUT_UNSET2", "sub/dir", "local", root=TMP)
check("2c uses the volume when one is genuinely writable",
      got == os.path.join(TMP, "sub/dir"), got)

# The fallback loses persistence, so it must be said out loud rather than
# quietly swallowing a scan that was expected to outlive the worker.
import io  # noqa: E402
from contextlib import redirect_stderr  # noqa: E402

buf = io.StringIO()
with redirect_stderr(buf):
    P.resolve("TEST_OUT_NOISY", "s", "l", root="/definitely/not/here")
check("2d the fallback is announced on stderr",
      "will NOT survive" in buf.getvalue(), buf.getvalue()[:120])

# ...but only once, or a per-job warning becomes noise nobody reads.
buf2 = io.StringIO()
with redirect_stderr(buf2):
    P.resolve("TEST_OUT_NOISY", "s", "l", root="/definitely/not/here")
check("2e and not repeated for the same variable", buf2.getvalue() == "",
      buf2.getvalue()[:80])


# ---- 3. ensure -------------------------------------------------------------
target = os.path.join(TMP, "paths-test-a", "b", "c")
check("3a creates nested directories", P.ensure(target) == target)
check("3b and it exists", os.path.isdir(target))
check("3c is idempotent", P.ensure(target) == target)

# A worker that cannot write its output directory should degrade rather than
# die: by the exporting stage the expensive work has already been done.
fallback = P.ensure("/proc/cannot/create/this")
check("3d an uncreatable path degrades instead of raising",
      os.path.isdir(fallback), fallback)
check("3e and lands somewhere local", fallback.startswith(TMP), fallback)


# ---- 4. the image must not hardcode the volume path -----------------------
# THE bug. An ENV in the Dockerfile overrides the runtime check completely,
# so the fallback above would never run.
dockerfile = open(os.path.join(HERE, "Dockerfile")).read()
check("4a Dockerfile does not set BUILDING_OUTPUT_DIR",
      "ENV BUILDING_OUTPUT_DIR" not in dockerfile)

handler_src = open(os.path.join(HERE, "handler.py")).read()
check("4b handler resolves its output dir at runtime",
      'paths.resolve("BUILDING_OUTPUT_DIR"' in handler_src)
check("4c handler no longer hardcodes the volume path",
      '"/runpod-volume/building-outputs")' not in handler_src)

roof_src = open(os.path.join(HERE, "roof.py")).read()
check("4d roof resolves its cache dir at runtime",
      'paths.resolve(' in roof_src)


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)

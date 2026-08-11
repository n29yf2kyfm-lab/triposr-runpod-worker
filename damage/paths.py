"""Where this worker writes things — pure stdlib.

A RunPod serverless endpoint only has /runpod-volume when a network volume is
attached to it, and attaching one is a deliberate, billed choice. The worker
must not depend on that: a JSON quote is a few kilobytes and has no business
requiring persistent storage to exist.

The first live job on the new endpoint hung in the exporting stage with the
worker exiting underneath it, against an endpoint created with no volume.
Whatever the precise mechanism, writing into a mount point that may not be
backed is not something to leave to chance, so the path is resolved against
what is actually writable at runtime.

Order:
  1. an explicit environment override — always wins, so a deployment that
     DOES attach a volume keeps using it
  2. /runpod-volume, if it exists and is genuinely writable
  3. a local directory, which always works and is simply not persistent

Persistence matters (RunPod job outputs expire in about 30 minutes and a scan
is worth more than that), so falling back is announced rather than silent.
"""
import os
import sys
import tempfile

RUNPOD_VOLUME = "/runpod-volume"

_warned = set()


def volume_available(root=RUNPOD_VOLUME):
    """True only if `root` exists AND a file can actually be created in it.

    Existence alone is not enough: a mount point can be present without being
    backed by anything, and that is the case worth defending against.
    """
    if not os.path.isdir(root):
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".writetest"):
            return True
    except OSError:
        return False


def resolve(env_var, volume_subdir, local_name, root=RUNPOD_VOLUME):
    """Pick a writable directory, preferring the network volume.

    `env_var` is checked first and used verbatim when set, so an endpoint with
    a volume attached is never second-guessed.
    """
    explicit = os.environ.get(env_var)
    if explicit:
        return explicit

    if volume_available(root):
        return os.path.join(root, volume_subdir)

    local = os.path.join(tempfile.gettempdir(), local_name)
    if env_var not in _warned:
        _warned.add(env_var)
        print(
            f"{env_var}: no writable {root}, falling back to {local}. Outputs "
            f"will NOT survive this worker — attach a network volume, or "
            f"configure object storage, if the artifacts need to outlive the "
            f"job.", file=sys.stderr)
    return local


def ensure(path):
    """Create a directory, falling back locally if it cannot be created.

    Returns the directory actually usable. A worker that cannot write its
    output directory should degrade rather than die mid-job — the expensive
    part of the work has already happened by then.
    """
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError as e:
        fallback = os.path.join(tempfile.gettempdir(),
                                os.path.basename(path.rstrip("/")) or "output")
        print(f"cannot create {path} ({type(e).__name__}: {e}); using "
              f"{fallback}", file=sys.stderr)
        os.makedirs(fallback, exist_ok=True)
        return fallback

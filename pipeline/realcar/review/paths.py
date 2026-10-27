"""Where the review's files are, and the few ways they are read and written.

F1K_HOME is the run's data folder: targets.json, results.jsonl, car_photos/,
the verdicts and labels. GLBMACHINE_HOME is the car machine's own (its rig
cache, its build folders). Nothing else is assumed: the tools refuse to run
without F1K_HOME rather than write somewhere unexpected.

Every shared file is written whole (to a .part file, then renamed), and the
results file is appended one complete line at a time, so a full disk or a
killed run never leaves half a record (the run of 27 October 2026 left a
truncated line that stopped the next run from starting).
"""
import contextlib
import fcntl
import hashlib
import json
import os
import time

REVIEW = os.path.dirname(os.path.abspath(__file__))
REALCAR = os.path.dirname(REVIEW)
REPO = os.path.dirname(os.path.dirname(REALCAR))


def home():
    h = os.environ.get("F1K_HOME")
    if not h:
        raise SystemExit("set F1K_HOME to the run's data folder (the one holding targets.json and results.jsonl)")
    return h


def f(*parts):
    """A path in the run's data folder."""
    return os.path.join(home(), *parts)


def machine_home():
    return os.environ.get("GLBMACHINE_HOME") or os.path.join(os.path.dirname(home()), "gmhome")


def load(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {} if default is None else default


def save(path, data, indent=1):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".part", "w") as fh:
        json.dump(data, fh, indent=indent)
    os.replace(path + ".part", path)


@contextlib.contextmanager
def lock(name):
    """Several agents at once: one writes a shared file at a time."""
    os.makedirs(home(), exist_ok=True)
    with open(f(f".{name}.lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def rows(path=None):
    """The results file as {key: row} (the last row of a key wins) and the
    number of lines that were not a whole record: read past, never fatal."""
    path = path or f("results.jsonl")
    out, bad = {}, 0
    if not os.path.exists(path):
        return out, 0
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                out[r["key"]] = r
            except (ValueError, KeyError, TypeError):
                bad += 1
    return out, bad


def append_row(row, path=None):
    """One complete line or nothing: a short write (a full disk) is cut back
    off, and the error raised for the caller to stop on."""
    path = path or f("results.jsonl")
    data = (json.dumps(row) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        start = os.fstat(fd).st_size
        try:
            n = os.write(fd, data)
            if n != len(data):
                raise OSError(28, "short write: the disk is full")
            os.fsync(fd)
        except OSError:
            os.ftruncate(fd, start)
            raise
    finally:
        os.close(fd)


def sha(path):
    """A file's fingerprint: what a verdict or a gold answer was made on."""
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def picture(key):
    """The studio picture of a key's build: the full one while it is there, else the small one."""
    return next((p for p in (f("hero_png", f"{key}.png"), f("hero", f"{key}.webp")) if os.path.exists(p)), None)


def photo(key):
    p = f("car_photos", f"{key}.jpg")
    return p if os.path.exists(p) else None


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def queue_rebuild(key, why):
    """A key whose build no longer matches its photo (a new photo, a new
    colour or side): it goes to needs_rebuild.json, which check.py and the
    runner's redo read, so it cannot be forgotten."""
    with lock("needs_rebuild"):
        q = load(f("needs_rebuild.json"), {})
        q[key] = {"why": why, "at": now()}
        save(f("needs_rebuild.json"), q)


def labelled(what, keys):
    """Keys whose side or colour was named again: off the needs_label list."""
    with lock("needs_label"):
        q = load(f("needs_label.json"))
        if any(k in (q.get(what) or {}) for k in keys):
            for k in keys:
                (q.get(what) or {}).pop(k, None)
            save(f("needs_label.json"), q)

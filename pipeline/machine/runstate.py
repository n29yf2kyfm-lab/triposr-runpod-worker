#!/usr/bin/env python3
"""runstate.py — make the local machine chain survive a container rollback.

WHAT THIS COST. The container reverts to an earlier snapshot without warning:
the git checkout jumps back, the scratchpad is gone, pip installs are gone. On
2026-08-20 it fired TWICE INSIDE ONE HOUR and killed `machine.py` mid-run both
times (~20 min a run), and both times the work was unrecoverable because every
intermediate — `views/`, `car_labels*.npy`, `car_final.glb` — lived only on
local disk. CLAUDE.md already carried the rule ("upload every work product to
Supabase the moment it validates, then drop the local copy"); the GPU-side
scripts follow it and the LOCAL chain never did. This module is that rule,
wired into the chain.

Three parts, each paid for by a named failure:

1. CHECKPOINTS THAT CANNOT GO STALE. Existence is NOT a valid skip test. This
   session already hit the failure it produces: `machine.py finish` silently
   consumed a STALE `car_labels_r.npy` after `seg_project` had been re-run
   alone, and the sheet that came out was a plausible-looking lie. So every
   stage records a SIGNATURE — sha256 of each input file, sha256 of the stage's
   own script, and the version of any external tool it shells out to — and a
   stage is skipped only when that signature still matches AND its outputs are
   present and structurally valid. Change an input, edit a stage, upgrade
   Blender: the checkpoint dies.
   The stale-labels trap needs one thing more, because the input that went
   stale did not itself CHANGE: `car_labels_r.npy` is byte-identical, it is
   merely derived from a `car_labels.npy` that has moved on. Every input is
   therefore traced back to the stage that PRODUCED it, and if that producer's
   own signature no longer matches, the run STOPS with the command to fix it.
   A resume that silently uses a stale intermediate is worse than no resume.

2. BUCKET MIRROR. Every artefact goes to `car-meshes/machine_runs/<tag>/` the
   moment it validates, with a MANIFEST recording sha256 + size, and `restore()`
   pulls back anything the local disk is missing. A wiped scratchpad then costs
   a download, not a re-run.
   Storage requires BOTH `apikey:` and `Authorization: Bearer` — with
   Authorization alone the bucket returns 403 "Invalid Compact JWS", which
   reads exactly like an expired key and has cost this project hours.

3. DEPS PREFLIGHT. A rollback wipes pip installs and the chain used to die one
   stage in with `ModuleNotFoundError: No module named 'torch'` — AFTER Blender
   had spent six minutes rendering views. Failing in two seconds beats failing
   in six minutes.

Run standalone:
  python3 runstate.py preflight [--fix]
  python3 runstate.py pull --work W --tag T      # bucket -> local, no compute
  python3 runstate.py status --work W [--tag T]
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENV_FILE = "/root/.alam3d_env"
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
PREFIX = "machine_runs"
STATE_NAME = ".machine_state.json"
MANIFEST_NAME = "MANIFEST.json"

# MEASURED 2026-08-20 against this bucket, do not re-derive: a plain object POST
# succeeds at EXACTLY 52,428,800 bytes (50 MiB) and returns
# 400/{"statusCode":"413","code":"EntityTooLarge"} at 52,428,801. The bucket's
# own `file_size_limit` is null, so this is the project-wide ceiling and no
# upload path (resumable included) gets past it.
# CLAUDE.md's "bucket 413s above ~25MB" note is WRONG by 2x — probed 5/24/26/40
# MB all 200. Anything over the ceiling is therefore SPLIT into parts and
# reassembled on restore, never skipped: a 51MB canon is exactly the artefact
# whose loss the rollback made expensive.
SB_MAX = 52_428_800
CHUNK = 48 * 1024 * 1024          # matches the repo's conservative MAX_OBJ

BODY_KINDS = {".glb": "glb", ".npy": "npy", ".json": "json"}


# --------------------------------------------------------------- environment
def load_env(path=ENV_FILE):
    """Populate missing credentials from the out-of-repo env file.

    Tools load this themselves rather than trusting the caller to source it —
    a relaunch that forgot cost a whole wave once (wave_render.load_env).
    Values already in the environment always win.
    """
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        name, sep, value = line.partition("=")
        if sep and not os.environ.get(name.strip()):
            os.environ[name.strip()] = value.strip().strip("'\"")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- preflight
# (module, pip name). OpenEXR ships Imath in the same distribution; PIL is
# pillow. seg_masks imports every one of these on its first line.
DEPS = [("torch", None), ("transformers", None), ("OpenEXR", None),
        ("Imath", None), ("trimesh", None), ("scipy", None), ("numpy", None),
        ("PIL", "pillow")]
# The local stack is CPU-only torch (measured present: 2.13.0+cpu) — pulling
# the default CUDA wheel here would download ~2.5GB for nothing.
FIX_CMDS = [
    [sys.executable, "-m", "pip", "install", "-q", "torch",
     "--index-url", "https://download.pytorch.org/whl/cpu"],
    [sys.executable, "-m", "pip", "install", "-q", "transformers", "trimesh",
     "scipy", "numpy", "OpenEXR", "pillow"],
]
HF_MODELS = ["models--IDEA-Research--grounding-dino-tiny",
             "models--facebook--sam-vit-base"]


def _import_probe():
    """Import every dependency in a SUBPROCESS and report per-module.

    In-process would be wrong twice: a broken native wheel takes the
    orchestrator down with a segfault instead of a message, and torch's import
    would then sit in the parent for the whole run.
    """
    src = ("import importlib,sys\n"
           "for m in %r:\n"
           "    try: importlib.import_module(m); print('OK', m)\n"
           "    except Exception as e: print('BAD', m, type(e).__name__, e)\n"
           % [m for m, _ in DEPS])
    p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    bad = {}
    for line in p.stdout.splitlines():
        if line.startswith("BAD "):
            _, mod, rest = line.split(" ", 2)
            bad[mod] = rest
    if p.returncode != 0 and not bad:          # segfault / interpreter died
        bad["<probe>"] = (p.stderr or "").strip()[:200] or f"rc={p.returncode}"
    return bad


def blender_version():
    """`blender --version` first line, or None. Cached per process."""
    if not hasattr(blender_version, "_v"):
        v = None
        if shutil.which("blender"):
            try:
                p = subprocess.run(["blender", "--version"], capture_output=True,
                                   text=True, timeout=60)
                v = (p.stdout or "").strip().splitlines()[0].strip() or None
            except Exception:
                v = None
        blender_version._v = v
    return blender_version._v


def preflight(need_blender=True, fix=False):
    """Assert the chain's dependencies BEFORE any stage burns minutes.

    Returns a dict of what was found. Exits 2 with the exact fix command when
    something is missing and --fix was not asked for (or did not work).
    """
    t0 = time.time()
    bad = _import_probe()
    if bad and fix:
        log("preflight: missing", ",".join(bad), "— reinstalling")
        for cmd in FIX_CMDS:
            log("+", " ".join(cmd))
            subprocess.run(cmd, check=False)
        bad = _import_probe()
    bl = blender_version() if need_blender else "n/a"
    hf = os.path.expanduser("~/.cache/huggingface/hub")
    cached = [m for m in HF_MODELS if os.path.isdir(os.path.join(hf, m))]
    if bad or (need_blender and not bl):
        for mod, err in sorted(bad.items()):
            print(f"  MISSING {mod}: {err}", file=sys.stderr)
        if need_blender and not bl:
            print("  MISSING blender (apt-get install -y blender)", file=sys.stderr)
        print("\nFIX (a rollback wipes pip installs — this is expected, not a bug):",
              file=sys.stderr)
        for cmd in FIX_CMDS:
            print("  " + " ".join(cmd), file=sys.stderr)
        print("  ...then re-run with --resume; finished stages are skipped.",
              file=sys.stderr)
        raise SystemExit(2)
    missing_hf = [m for m in HF_MODELS if m not in cached]
    if missing_hf:
        # Not fatal: seg_masks downloads them. Worth a line, because a rollback
        # wipes this cache too and the download then happens INSIDE the 20-minute
        # stage — if the network is down that is where you find out.
        log("preflight: HF weights not cached, seg_masks will download",
            ",".join(m.split("--")[-1] for m in missing_hf))
    log(f"preflight OK in {time.time()-t0:.1f}s "
        f"(torch/transformers/OpenEXR/trimesh/scipy, blender={bl})")
    return {"blender": bl, "hf_cached": cached}


# ------------------------------------------------------------------ digests
_SHA_MEMO = {}


def sha_file(path):
    """sha256 of one file, memoised on (path, size, mtime_ns).

    The memo matters: `views/` is hashed once as seg_views' output and again as
    seg_masks' input, and it is ~16MB of EXR.
    """
    st = os.stat(path)
    k = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    if k in _SHA_MEMO:
        return _SHA_MEMO[k]
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    _SHA_MEMO[k] = h.hexdigest()
    return _SHA_MEMO[k]


class Art:
    """One artefact: a file, or a FILTERED set of files inside a directory.

    The filter is not decoration. `seg_views` and `seg_masks` both write into
    the same `views/` directory, so without a per-stage pattern one stage's
    checkpoint would be invalidated by the other's output and neither could
    ever be skipped. Note also that the obvious pattern for the view renders
    (`view_*.png`) also matches the MASKS (`view_00_glass.png`) — hence
    anchored regexes, not globs.
    """

    def __init__(self, path, pat=None, min_files=0, kind=None):
        self.path = os.path.abspath(path)
        self.pat = re.compile(pat) if pat else None
        self.min_files = min_files
        self.kind = kind or (BODY_KINDS.get(os.path.splitext(path)[1], "file")
                             if pat is None else "set")

    def __repr__(self):
        return f"Art({os.path.basename(self.path)}{'/'+self.pat.pattern if self.pat else ''})"

    def members(self):
        """Concrete files this artefact covers, relative-name sorted."""
        if self.pat is None:
            return [self.path] if os.path.isfile(self.path) else []
        if not os.path.isdir(self.path):
            return []
        return [os.path.join(self.path, n) for n in sorted(os.listdir(self.path))
                if self.pat.search(n)]

    def digest(self):
        """Content hash, or None when the artefact is absent."""
        mem = self.members()
        if not mem:
            return None
        if self.pat is None:
            return sha_file(mem[0])
        h = hashlib.sha256()
        for f in mem:
            h.update(f"{os.path.basename(f)} {os.path.getsize(f)} {sha_file(f)}\n"
                     .encode())
        return h.hexdigest()

    def validate(self):
        """Structural check. Returns None if fine, else the reason it is not.

        Deliberately cheap and stdlib-only — this runs before the deps
        preflight has proven numpy/trimesh exist, and a validator that needs
        the very stack a rollback just deleted is no validator at all.
        """
        mem = self.members()
        if not mem:
            return "absent"
        if len(mem) < self.min_files:
            return f"only {len(mem)} of {self.min_files} files"
        for f in mem:
            if os.path.getsize(f) == 0:
                return f"{os.path.basename(f)} is empty"
        if self.kind == "glb":
            with open(mem[0], "rb") as fh:
                if fh.read(4) != b"glTF":
                    return "not a GLB (bad magic)"
            if os.path.getsize(mem[0]) < 1024:
                return "GLB truncated"
        elif self.kind == "npy":
            with open(mem[0], "rb") as fh:
                if fh.read(6) != b"\x93NUMPY":
                    return "not a .npy (bad magic)"
        elif self.kind == "json":
            try:
                json.load(open(mem[0]))
            except Exception as e:
                return f"unreadable json: {e}"
        return None


# ------------------------------------------------------------ bucket mirror
def _key():
    k = os.environ.get("SB_KEY")
    if not k:
        raise RuntimeError("SB_KEY not set (set -a; . /root/.alam3d_env; set +a)")
    return k


def _hdr(extra=None):
    # BOTH headers. Authorization alone -> 403 "Invalid Compact JWS", which
    # reads exactly like an expired key. Hours have gone into that.
    h = {"apikey": _key(), "Authorization": f"Bearer {_key()}"}
    h.update(extra or {})
    return h


def sb_post(path, blob, ctype="application/octet-stream", timeout=900):
    rq = urllib.request.Request(
        f"{SB}/storage/v1/object/{BUCKET}/{path}", data=blob, method="POST",
        headers=_hdr({"Content-Type": ctype, "x-upsert": "true"}))
    return urllib.request.urlopen(rq, timeout=timeout).status


def sb_fetch(path, timeout=900):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{BUCKET}/{path}",
                                headers=_hdr())
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return r.read()


def sb_put_file(local, remote):
    """Upload one file, splitting over the measured 50 MiB ceiling.

    Returns the number of parts (1 = whole object). Raises on HTTP failure —
    the caller decides whether a mirror failure is fatal, but it is never
    swallowed: an artefact that silently did not upload is an artefact that
    does not survive the next rollback, and you would not know until it
    mattered.
    """
    size = os.path.getsize(local)
    if size <= CHUNK:
        sb_post(remote, open(local, "rb").read())
        return 1
    n = 0
    with open(local, "rb") as fh:
        while True:
            blk = fh.read(CHUNK)
            if not blk:
                break
            sb_post(f"{remote}.part{n:03d}", blk)
            n += 1
    return n


def sb_get_file(remote, local, parts=1):
    tmp = local + ".partial"
    os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
    with open(tmp, "wb") as out:
        if parts <= 1:
            out.write(sb_fetch(remote))
        else:
            for i in range(parts):
                out.write(sb_fetch(f"{remote}.part{i:03d}"))
    os.replace(tmp, local)


# -------------------------------------------------------------------- runner
class Stage:
    """One chain step, declared rather than called.

    inputs/outputs are Art()s; `cmd` is the argv the step already ran as, so
    the shape of the existing chain is unchanged — only its bookkeeping is new.
    """

    def __init__(self, name, script, cmd, inputs, outputs, uses=()):
        self.name, self.script, self.cmd = name, script, cmd
        self.inputs, self.outputs, self.uses = inputs, outputs, uses


class Runner:
    """Executes stages with checkpoints, staleness refusal and bucket mirror."""

    def __init__(self, work, tag, resume=True, mirror=True, force=(), quiet=False):
        self.work = os.path.abspath(work)
        self.tag = tag
        self.resume = resume
        self.mirror = mirror
        self.force = set(force or ())
        self.quiet = quiet
        self.state_path = os.path.join(self.work, STATE_NAME)
        os.makedirs(self.work, exist_ok=True)
        self.state = {}
        if os.path.exists(self.state_path):
            try:
                self.state = json.load(open(self.state_path))
            except Exception as e:
                log("warn: unreadable state file, starting clean:", e)
        self.manifest = self.state.setdefault("_manifest", {})
        self.producer = {}          # artefact key -> stage name (built by plan)
        self.mirror_fail = []       # (artefact, reason) — reported at the end
        self.ran, self.skipped = [], []

    # ---- paths ----------------------------------------------------------
    def _rel(self, path):
        """Manifest key: work-relative where possible, else absolute.

        An input like the 51MB canon commonly sits OUTSIDE the work dir; it is
        still mirrored, because regenerating it needs the raw generator output
        pulled back from the bucket and another canon.py pass.
        """
        p = os.path.abspath(path)
        if p.startswith(self.work + os.sep):
            return os.path.relpath(p, self.work)
        return p

    def _remote(self, rel):
        safe = rel.replace(os.sep, "/").lstrip("/")
        if safe.startswith("../") or os.path.isabs(rel):
            safe = "_abs/" + safe.replace("../", "").lstrip("/")
        return f"{PREFIX}/{self.tag}/{safe}"

    # ---- signatures -----------------------------------------------------
    def _sig(self, st):
        sig = {"script": sha_file(st.script) if os.path.exists(st.script) else None,
               "inputs": {}}
        for a in st.inputs:
            sig["inputs"][self._rel(a.path) + ("::" + a.pat.pattern if a.pat else "")] = a.digest()
        if "blender" in st.uses:
            sig["blender"] = blender_version()
        return sig

    def _entry_valid(self, st):
        """Is this stage's recorded checkpoint still true RIGHT NOW?

        Three ways it can be false: no entry, the signature moved (input edited,
        stage script edited, Blender upgraded), or an output that is gone or
        structurally broken (a rollback mid-write leaves exactly that).
        """
        e = self.state.get(st.name)
        if not e:
            return False, "no checkpoint"
        if e.get("sig") != self._sig(st):
            return False, "inputs/script changed"
        for a in st.outputs:
            why = a.validate()
            if why:
                return False, f"output {os.path.basename(a.path)}: {why}"
            if e.get("outputs", {}).get(self._rel(a.path)) != a.digest():
                return False, f"output {os.path.basename(a.path)} changed on disk"
        return True, "fresh"

    def _assert_upstream_fresh(self, st, plan):
        """THE STALE-INTERMEDIATE GATE — the one this session actually paid for.

        `machine.py finish` consumed a `car_labels_r.npy` that was byte-perfect
        and semantically dead: `seg_project` had been re-run alone, so the file
        it was derived from had moved on. Hashing the input cannot see that —
        the input did not change. So walk each input back to the stage that
        PRODUCED it and require that producer's own checkpoint to still hold.
        If it does not, and the producer is not in this invocation's plan to be
        rebuilt, stop and name the command that fixes it.
        """
        names = {s.name for s in plan}
        for a in st.inputs:
            src = self.producer.get(self._rel(a.path))
            if not src or src == st.name or src in names:
                continue
            ok, why = self._entry_valid_by_name(src)
            if not ok:
                raise SystemExit(
                    f"STALE UPSTREAM: {st.name} would consume "
                    f"{os.path.basename(a.path)}, produced by '{src}', whose own "
                    f"checkpoint is no longer valid ({why}).\n"
                    f"  The file on disk is intact but derived from inputs that "
                    f"have moved on — this is the trap that silently shipped a "
                    f"wrong sheet on 2026-08-20.\n"
                    f"  Fix: re-run the whole chain for this work dir "
                    f"(machine.py all ...), or --force {src} first.")

    def _entry_valid_by_name(self, name):
        st = self._by_name.get(name)
        if st is None:
            return True, "not in plan"      # cannot judge; do not block
        return self._entry_valid(st)

    # ---- mirror ---------------------------------------------------------
    def _mirror_art(self, a):
        if not self.mirror:
            return
        for f in a.members():
            rel = self._rel(f)
            rec = self.manifest.get(rel)
            sha = sha_file(f)
            if rec and rec.get("sha256") == sha:
                continue                              # already up there
            remote = self._remote(rel)
            try:
                parts = sb_put_file(f, remote)
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:120]}"
                self.mirror_fail.append((rel, msg))
                log(f"  MIRROR-FAIL {rel}: {msg}")
                continue
            self.manifest[rel] = {"remote": remote, "sha256": sha,
                                  "size": os.path.getsize(f), "parts": parts,
                                  "at": int(time.time())}
            if not self.quiet:
                log(f"  mirrored {rel} -> {remote}"
                    + (f" ({parts} parts)" if parts > 1 else ""))

    def _push_state(self):
        """Write the ledger locally, then mirror the ledger + manifest.

        Written atomically: a rollback landing mid-write would otherwise leave a
        truncated ledger, and the next run would silently start from scratch.
        """
        tmp = self.state_path + ".tmp"
        json.dump(self.state, open(tmp, "w"), indent=1)
        os.replace(tmp, self.state_path)
        if not self.mirror:
            return
        try:
            blob = json.dumps(self.state, indent=1).encode()
            sb_post(f"{PREFIX}/{self.tag}/{STATE_NAME}", blob, "application/json")
            sb_post(f"{PREFIX}/{self.tag}/{MANIFEST_NAME}",
                    json.dumps({"tag": self.tag, "work": self.work,
                                "updated": int(time.time()),
                                "files": self.manifest}, indent=1).encode(),
                    "application/json")
        except Exception as e:
            self.mirror_fail.append((STATE_NAME, f"{type(e).__name__}: {str(e)[:120]}"))
            log("  MIRROR-FAIL state:", str(e)[:120])

    def restore(self):
        """Pull anything the bucket has and this disk does not. Idempotent.

        This is the rollback path: an EMPTY work dir plus the run's tag is
        enough to get every finished stage back, because the ledger is mirrored
        alongside the artefacts.
        """
        if not self.mirror:
            return 0
        try:
            man = json.loads(sb_fetch(f"{PREFIX}/{self.tag}/{MANIFEST_NAME}",
                                      timeout=120).decode())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return 0                       # nothing mirrored yet — normal
            log("restore: manifest fetch failed:", e); return 0
        except Exception as e:
            log("restore: manifest fetch failed:", str(e)[:120]); return 0
        got = 0
        for rel, rec in sorted(man.get("files", {}).items()):
            local = rel if os.path.isabs(rel) else os.path.join(self.work, rel)
            if os.path.exists(local) and sha_file(local) == rec["sha256"]:
                continue
            try:
                sb_get_file(rec["remote"], local, rec.get("parts", 1))
            except Exception as e:
                log(f"  restore-FAIL {rel}: {str(e)[:120]}"); continue
            if sha_file(local) != rec["sha256"]:
                # A corrupted download that is allowed to stand is a stale
                # intermediate by another name.
                os.remove(local)
                log(f"  restore-FAIL {rel}: sha256 mismatch, removed"); continue
            got += 1
            log(f"  restored {rel} ({rec['size']}B"
                + (f", {rec['parts']} parts" if rec.get("parts", 1) > 1 else "") + ")")
        self.manifest.update(man.get("files", {}))
        if not os.path.exists(self.state_path):
            try:
                blob = sb_fetch(f"{PREFIX}/{self.tag}/{STATE_NAME}", timeout=120)
                open(self.state_path, "wb").write(blob)
                self.state = json.loads(blob.decode())
                self.manifest = self.state.setdefault("_manifest", {})
                self.manifest.update(man.get("files", {}))
                log("  restored checkpoint ledger")
            except Exception as e:
                log("restore: no ledger in bucket:", str(e)[:90])
        if got:
            log(f"restore: {got} artefact(s) pulled from "
                f"{BUCKET}/{PREFIX}/{self.tag}/")
        return got

    # ---- execution ------------------------------------------------------
    def run(self, plan):
        self._by_name = {s.name: s for s in plan}
        for s in plan:                       # who makes what, for the stale gate
            for a in s.outputs:
                self.producer.setdefault(self._rel(a.path), s.name)
        # Producers from EARLIER invocations matter too: `finish` must know that
        # car_labels_r.npy came from seg_refine even though seg_refine is not in
        # its plan. The ledger carries that.
        for name, e in self.state.items():
            if name.startswith("_"):
                continue
            for rel in e.get("outputs", {}):
                self.producer.setdefault(rel, name)

        for st in plan:
            if st.name in self.force:
                log(f"[{st.name}] forced")
            elif self.resume:
                ok, why = self._entry_valid(st)
                if ok:
                    log(f"[{st.name}] SKIP (checkpoint fresh)")
                    self.skipped.append(st.name)
                    self._mirror_art_all(st)     # cheap no-op once mirrored
                    continue
                log(f"[{st.name}] run ({why})")
            self._assert_upstream_fresh(st, plan)
            t0 = time.time()
            print("+", " ".join(st.cmd), flush=True)
            subprocess.run(st.cmd, check=True)
            for a in st.outputs:
                why = a.validate()
                if why:
                    raise SystemExit(f"{st.name}: output {a} invalid after run "
                                     f"({why}) — refusing to checkpoint it")
            self.state[st.name] = {
                "sig": self._sig(st),
                "outputs": {self._rel(a.path): a.digest() for a in st.outputs},
                "secs": round(time.time() - t0, 1),
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self.ran.append(st.name)
            self._mirror_art_all(st)
            self._push_state()
            log(f"[{st.name}] done in {time.time()-t0:.1f}s")
        self._push_state()
        return self

    def _mirror_art_all(self, st):
        for a in list(st.inputs) + list(st.outputs):
            self._mirror_art(a)

    def report(self):
        log(f"stages ran={self.ran or '-'} skipped={self.skipped or '-'}")
        if self.mirror_fail:
            # Loud on purpose. Unmirrored == unprotected, and the whole point of
            # this module is that you find that out now rather than after the
            # next rollback.
            log(f"NOT PROTECTED: {len(self.mirror_fail)} artefact(s) failed to "
                f"mirror — a rollback loses them:")
            for rel, why in self.mirror_fail:
                log(f"   {rel}: {why}")
        elif self.mirror:
            log(f"mirrored to {BUCKET}/{PREFIX}/{self.tag}/ "
                f"({len(self.manifest)} artefacts)")


# ---------------------------------------------------------------------- CLI
if __name__ == "__main__":
    import argparse
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preflight", "pull", "status"])
    ap.add_argument("--work")
    ap.add_argument("--tag", default="machine")
    ap.add_argument("--fix", action="store_true", help="pip install what is missing")
    a = ap.parse_args()
    if a.cmd == "preflight":
        preflight(fix=a.fix)
    elif a.cmd == "pull":
        if not a.work:
            raise SystemExit("--work required")
        Runner(a.work, a.tag).restore()
    else:
        st = {}
        p = os.path.join(a.work or ".", STATE_NAME)
        if os.path.exists(p):
            st = json.load(open(p))
        for k, v in st.items():
            if k.startswith("_"):
                continue
            print(f"{k:14s} {v.get('at','?')}  {v.get('secs','?')}s  "
                  f"{len(v.get('outputs', {}))} output(s)")
        print(f"{len(st.get('_manifest', {}))} artefact(s) in the manifest")

#!/usr/bin/env python3
"""blender_cmd.py — thin client for the resident Blender session.

Talks to `blender_live.py` over its unix socket: one newline-terminated JSON
request per connection, one JSON reply. Nothing here holds state — the session
does — so the client can die, be killed, or be a different agent each time.

  # start a session with the car already loaded (blocks until it answers ping)
  python3 blender_cmd.py start --glb car.glb --sock /tmp/golf.sock

  # then, from anywhere, as many times as you like
  python3 blender_cmd.py info   --sock /tmp/golf.sock
  python3 blender_cmd.py select --sock /tmp/golf.sock --regex 'glass|window'
  python3 blender_cmd.py snapshot --sock /tmp/golf.sock --name pre --mode blend
  python3 blender_cmd.py apply  --sock /tmp/golf.sock --repair translate --dz 0.01
  python3 blender_cmd.py render --sock /tmp/golf.sock --out /tmp/a.png --az 45
  python3 blender_cmd.py undo   --sock /tmp/golf.sock
  python3 blender_cmd.py stop   --sock /tmp/golf.sock

  # and the whole session again, from its own log, as a batch
  python3 blender_cmd.py replay /tmp/golf.sock.jsonl --glb car.glb

Values are parsed as JSON where possible and as strings otherwise, so
`--dz 0.01` is a float, `--name pre` is a string and `--names '["a","b"]'` is a
list. `--json '{...}'` supplies a whole request body.

Exit status is 0 only when the session replied `status: ok`, so a shell chain
can gate on it.

Importable too:
    from blender_cmd import Session
    s = Session("/tmp/golf.sock");  s.cmd("info")
"""
import json
import os
import socket
import subprocess
import sys
import time

DEFAULT_SOCK = os.environ.get("BLENDER_LIVE_SOCK", "/tmp/blender_live.sock")
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "blender_live.py")


def short_sock(path):
    """MUST MATCH blender_live.short_sock — see its docstring. AF_UNIX sun_path
    is capped at 108 bytes, so long session paths are bound at a hashed /tmp
    address. This is only the FALLBACK: once the session is up, `.ready` records
    the real bind address and _bind_path prefers it, so the two halves cannot
    drift apart in practice."""
    if len(path.encode()) <= 100:
        return path
    import hashlib
    return "/tmp/bl-" + hashlib.sha1(path.encode()).hexdigest()[:16] + ".sock"


def _bind_path(sock):
    try:
        with open(sock + ".ready") as fh:
            return json.load(fh).get("bind") or short_sock(sock)
    except (OSError, ValueError):
        return short_sock(sock)


class Session:
    """one live Blender session, addressed by its socket path"""

    def __init__(self, sock=DEFAULT_SOCK, timeout=1800):
        self.sock = os.path.abspath(sock)
        self.timeout = timeout

    def cmd(self, _op, **kw):
        # `op` is the request's reserved key. Taking it positionally as `_op`
        # keeps `cmd("apply", repair="translate")` working, and the explicit
        # guard turns what was a baffling `got multiple values for argument
        # 'op'` TypeError into a sentence that says what to do instead.
        if "op" in kw:
            raise ValueError(
                "'op' is the request's own field — a nested op cannot be sent. "
                "For a repair use repair=<name> (e.g. apply repair=translate).")
        req = dict(kw)
        req["op"] = _op
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # a render can legitimately take minutes on CPU CYCLES; the timeout is
        # generous on purpose. It exists so a wedged session is detectable, not
        # to bound normal work.
        c.settimeout(self.timeout)
        try:
            c.connect(_bind_path(self.sock))
            c.sendall((json.dumps(req) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = c.recv(65536)
                if not chunk:
                    break
                buf += chunk
        finally:
            c.close()
        if not buf.strip():
            raise ConnectionError(
                f"no reply from {self.sock} (op={op}) — the session may have "
                "died; check its stdout log")
        return json.loads(buf.split(b"\n", 1)[0].decode())

    def alive(self):
        try:
            return self.cmd("ping").get("status") == "ok"
        except (OSError, ConnectionError):
            return False


def start(sock, glb=None, log=None, blender=None, extra=(), wait=180):
    """launch a session and block until it actually answers.

    Waiting on the READY file alone is not enough — it is written after
    listen(), but the process could still die on the preload. We poll with a
    real ping, which is the only proof the session is usable.
    """
    sock = os.path.abspath(sock)
    ready, stdout_log = sock + ".ready", (log or sock) + ".out"
    s = Session(sock, timeout=30)
    if s.alive():
        raise SystemExit(f"REFUSED: a live session already owns {sock}. "
                         "Use it, or `stop` it first.")
    os.makedirs(os.path.dirname(sock) or "/", exist_ok=True)
    for p in (_bind_path(sock), ready):
        if os.path.exists(p):
            os.unlink(p)                    # stale files from a killed session
    cmd = [blender or os.environ.get("BLENDER", "blender"), "-b",
           "--python", SERVER, "--", "--sock", sock]
    if log:
        cmd += ["--log", log]
    if glb:
        cmd += ["--glb", os.path.abspath(glb)]
    cmd += list(extra)
    fh = open(stdout_log, "ab")
    fh.write(f"\n=== start {time.strftime('%F %T')} : {' '.join(cmd)}\n"
             .encode())
    fh.flush()
    # start_new_session so the session outlives this client, and every later
    # client invocation, exactly as a resident scene must.
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < wait:
        if proc.poll() is not None:
            raise SystemExit(f"blender exited rc={proc.returncode} before "
                             f"becoming ready — see {stdout_log}")
        if os.path.exists(ready) and s.alive():
            info = s.cmd("ping")["result"]
            info.update({"sock": sock, "pid": proc.pid, "stdout": stdout_log,
                         "startup_s": round(time.time() - t0, 2)})
            return info
        time.sleep(0.25)
    raise SystemExit(f"session did not become ready in {wait}s — see {stdout_log}")


def replay(logpath, sock, glb=None, skip=("quit",), dry=False):
    """re-run a logged session. The log records op+args for every request, so
    a live repair is reproducible as a batch — a session whose work cannot be
    reproduced is a liability."""
    entries = [json.loads(x) for x in open(logpath).read().splitlines()
               if x.strip()]
    plan = [e for e in entries if e.get("op") not in skip]
    print(f"replay: {len(plan)} of {len(entries)} logged commands "
          f"({len(entries) - len(plan)} skipped: {','.join(skip)})")
    if dry:
        for e in plan:
            print(f"  {e['seq']:>3} {e['op']} {json.dumps(e.get('args', {}))}")
        return 0
    s = Session(sock)
    if not s.alive():
        print("no session on", sock, "— starting one")
        start(sock, glb=glb)
    bad = 0
    for e in plan:
        r = s.cmd(e["op"], **e.get("args", {}))
        st = r.get("status")
        bad += st != "ok"
        print(f"  {e['seq']:>3} {e['op']:<10} {st:<5} {r.get('ms', 0):>6} ms"
              + ("  " + r.get("message", "") if st != "ok" else ""))
    return 1 if bad else 0


def _parse(args):
    """--k v pairs -> dict, JSON-coerced where possible"""
    out, i = {}, 0
    while i < len(args):
        a = args[i]
        if not a.startswith("--"):
            raise SystemExit(f"expected --flag, got {a!r}")
        k = a[2:].replace("-", "_")
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            v = args[i + 1]
            i += 2
        else:
            v = "true"                      # bare --flag means true
            i += 1
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    op, rest = argv[0], argv[1:]
    # positionals are the leading tokens only; everything from the first
    # --flag onward belongs to _parse. Splitting by index-of-value instead
    # would mis-handle a repeated token, which is the kind of quiet parsing
    # bug that makes a tool untrustworthy.
    cut = next((i for i, a in enumerate(rest) if a.startswith("--")), len(rest))
    positional, kw = rest[:cut], _parse(rest[cut:])
    if "json" in kw:
        kw.update(kw.pop("json"))
    sock = kw.pop("sock", DEFAULT_SOCK)

    if op == "start":
        info = start(sock, glb=kw.pop("glb", None), log=kw.pop("log", None),
                     blender=kw.pop("blender", None),
                     extra=[str(x) for kv in kw.items() for x in
                            (f"--{kv[0].replace('_', '-')}", kv[1])])
        print(json.dumps(info, indent=1))
        return 0
    if op == "replay":
        return replay(positional[0], sock, glb=kw.get("glb"),
                      dry=bool(kw.get("dry")))
    if op == "stop":
        s = Session(sock, timeout=60)
        if not s.alive():
            print(json.dumps({"status": "ok", "note": "no session on " + sock}))
            return 0
        snapdir = s.cmd("snapshots")["result"]["dir"]
        bind = _bind_path(sock)             # resolve BEFORE quit removes .ready
        try:
            s.cmd("quit")
        except (OSError, ConnectionError):
            pass                            # the session closes the socket as
        for _ in range(40):                 # it goes; that is not an error
            if not os.path.exists(bind):
                break
            time.sleep(0.25)
        if kw.get("clean"):
            import shutil
            shutil.rmtree(snapdir, ignore_errors=True)
        print(json.dumps({"status": "ok", "stopped": sock,
                          "cleaned": bool(kw.get("clean"))}))
        return 0

    s = Session(sock, timeout=float(kw.pop("timeout", 1800)))
    try:
        r = s.cmd(op, **kw)
    except ValueError as e:                 # reserved-field misuse, said plainly
        print(json.dumps({"status": "error", "error": "BadArgument",
                          "message": str(e)}))
        return 2
    except (FileNotFoundError, ConnectionRefusedError):
        print(json.dumps({"status": "error", "error": "NoSession",
                          "message": f"nothing listening on {sock}; "
                                     "run `blender_cmd.py start` first"}))
        return 2
    print(json.dumps(r, indent=1))
    return 0 if r.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

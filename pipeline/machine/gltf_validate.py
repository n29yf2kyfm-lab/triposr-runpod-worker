#!/usr/bin/env python3
"""
gltf_validate.py -- run the OFFICIAL Khronos glTF-Validator over a GLB/glTF and
report every error and warning in structured form.

WHY THIS FILE EXISTS
--------------------
The Class-A spec allows ZERO validator errors and requires every warning to be
documented and justified. Nothing in this repo was checking that. `publish_batch`
gates on catalogue metadata; `glb_doctor` checks our own invariants. Neither runs
a conformance check against the glTF 2.0 specification.

WHAT THE VALIDATOR IS (and what it is NOT)
------------------------------------------
  * IS:  the `gltf-validator` npm package -- Khronos Group, Apache-2.0, the
         reference implementation compiled from Dart to JS. It ships a LIBRARY
         only ("bin": null in its package.json), so a global install leaves NO
         command on PATH. `_gltf_validate_shim.js` next to this file supplies the
         CLI. Install with:  npm install -g gltf-validator
  * IS NOT: `gltf-transform`. That is an optimise/transform toolkit, already
         installed globally here, and it has no conformance-validation mode. Do
         not conflate them -- an earlier plan in this project did.

SEVERITY LADDER (Khronos codes, straight from validation.schema.json)
    0 = Error        -> hard fail. Spec violation.
    1 = Warning      -> must be justified in the allowlist to pass --strict.
    2 = Information  -> recorded, never fails.
    3 = Hint         -> recorded, never fails.

DOCUMENTED-WARNING ALLOWLIST
----------------------------
Warnings are not waved through silently. `--allow FILE` takes a JSON file of
{"CODE": "why this warning is acceptable"} and a warning only passes if its code
carries a non-empty justification. An undocumented warning fails --strict. This
is the mechanism that makes "each warning is documented and justified" an
enforced property rather than a promise.

EXIT CODES
    0  clean (no errors; under --strict, no undocumented warnings either)
    1  validation issues that fail the configured gate
    2  could not run (missing file, validator not installed)

USAGE
    python3 pipeline/machine/gltf_validate.py car.glb
    python3 pipeline/machine/gltf_validate.py car.glb --strict --allow warnings.json
    python3 pipeline/machine/gltf_validate.py car.glb --json report.json --quiet
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "_gltf_validate_shim.js")

SEVERITY = {0: "ERROR", 1: "WARNING", 2: "INFO", 3: "HINT"}

# Search path for a globally-installed gltf-validator, used only to produce a
# helpful message when it is absent.
GLOBAL_CANDIDATES = (
    "/opt/node22/lib/node_modules/gltf-validator",
    "/usr/lib/node_modules/gltf-validator",
    "/usr/local/lib/node_modules/gltf-validator",
)


class ValidatorUnavailable(RuntimeError):
    pass


def _find_node():
    node = shutil.which("node")
    if node:
        return node
    for p in ("/opt/node22/bin/node", "/usr/bin/node", "/usr/local/bin/node"):
        if os.path.exists(p):
            return p
    raise ValidatorUnavailable("node not found on PATH")


def validator_present():
    """True when the Khronos validator package can be resolved."""
    return any(os.path.isdir(p) for p in GLOBAL_CANDIDATES)


def run_validator(path, max_issues=0):
    """Invoke the Khronos validator. Returns the raw report dict.

    Raises ValidatorUnavailable if the toolchain is missing, so a caller can
    distinguish "could not test" from "tested and failed". Those are different
    claims and the spec's honesty rule requires keeping them apart.
    """
    if not os.path.exists(path):
        raise ValidatorUnavailable("no such file: %s" % path)
    if not os.path.exists(SHIM):
        raise ValidatorUnavailable("missing shim: %s" % SHIM)
    if not validator_present():
        raise ValidatorUnavailable(
            "the Khronos glTF-Validator is not installed. "
            "Run:  npm install -g gltf-validator"
        )
    node = _find_node()
    proc = subprocess.run(
        [node, SHIM, path, str(max_issues)],
        capture_output=True, text=True,
    )
    if proc.returncode == 2:
        raise ValidatorUnavailable(proc.stderr.strip() or "validator shim failed")
    if proc.returncode != 0:
        raise ValidatorUnavailable(
            "validator exited %d: %s" % (proc.returncode, proc.stderr.strip())
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ValidatorUnavailable("unparseable validator output: %s" % e)


def structure(report, path):
    """Reduce the raw Khronos report to a structured, diff-friendly summary.

    Messages are grouped by (severity, code) with a representative pointer and
    an occurrence count, because a real asset produces the SAME code hundreds of
    times (30 identical non-unit-normal errors on our Golf master) and a flat
    list buries the signal.
    """
    issues = report.get("issues", {})
    messages = issues.get("messages", [])

    groups = OrderedDict()
    for m in messages:
        key = (m["severity"], m["code"])
        g = groups.setdefault(key, {
            "severity": SEVERITY.get(m["severity"], str(m["severity"])),
            "code": m["code"],
            "count": 0,
            "message": m["message"],
            "pointers": [],
        })
        g["count"] += 1
        if len(g["pointers"]) < 5:
            g["pointers"].append(m.get("pointer", m.get("offset")))

    ordered = sorted(groups.values(), key=lambda g: (
        {"ERROR": 0, "WARNING": 1, "INFO": 2, "HINT": 3}.get(g["severity"], 9),
        -g["count"],
    ))

    info = report.get("info", {}) or {}
    return {
        "file": os.path.abspath(path),
        "sizeBytes": os.path.getsize(path) if os.path.exists(path) else None,
        "validatorVersion": report.get("validatorVersion"),
        "validatedAt": report.get("validatedAt"),
        "mimeType": report.get("mimeType"),
        "counts": {
            "errors": issues.get("numErrors", 0),
            "warnings": issues.get("numWarnings", 0),
            "infos": issues.get("numInfos", 0),
            "hints": issues.get("numHints", 0),
        },
        "truncated": issues.get("truncated", False),
        "assetInfo": {
            "generator": info.get("generator"),
            "version": info.get("version"),
            "extensionsUsed": info.get("extensionsUsed", []),
            "extensionsRequired": info.get("extensionsRequired", []),
            "drawCallCount": info.get("drawCallCount"),
            "totalVertexCount": info.get("totalVertexCount"),
            "totalTriangleCount": info.get("totalTriangleCount"),
            "materialCount": info.get("materialCount"),
            "hasMorphTargets": info.get("hasMorphTargets"),
            "hasSkins": info.get("hasSkins"),
            "hasTextures": info.get("hasTextures"),
            "maxAttributes": info.get("maxAttributes"),
            "maxUVs": info.get("maxUVs"),
        },
        "groups": ordered,
    }


def gate(summary, allow=None, strict=False):
    """Apply the pass/fail policy. Returns (ok, reasons)."""
    allow = allow or {}
    reasons = []
    ok = True

    if summary["counts"]["errors"] > 0:
        ok = False
        codes = sorted({g["code"] for g in summary["groups"] if g["severity"] == "ERROR"})
        reasons.append(
            "%d validator ERROR(s) -- the spec allows zero. Codes: %s"
            % (summary["counts"]["errors"], ", ".join(codes))
        )

    if strict:
        undocumented = [
            g["code"] for g in summary["groups"]
            if g["severity"] == "WARNING" and not str(allow.get(g["code"], "")).strip()
        ]
        if undocumented:
            ok = False
            reasons.append(
                "undocumented WARNING(s) under --strict: %s. Add a justification "
                "for each to the --allow file." % ", ".join(sorted(set(undocumented)))
            )

    if summary["truncated"]:
        reasons.append(
            "NOTE: validator output was TRUNCATED -- counts are a lower bound. "
            "Re-run with --max-issues 0."
        )
    return ok, reasons


def render(summary, allow=None, reasons=None, ok=True):
    allow = allow or {}
    L = []
    A = L.append
    c = summary["counts"]
    A("=" * 78)
    A("KHRONOS glTF VALIDATOR REPORT")
    A("=" * 78)
    A("file      : %s" % summary["file"])
    if summary["sizeBytes"] is not None:
        A("size      : %.2f MB (%d bytes)" % (summary["sizeBytes"] / 1e6, summary["sizeBytes"]))
    A("validator : %s   (Khronos Group, Apache-2.0)" % summary["validatorVersion"])
    A("validated : %s" % summary["validatedAt"])
    ai = summary["assetInfo"]
    if ai.get("totalTriangleCount") is not None:
        A("geometry  : %s triangles, %s vertices, %s draw calls, %s materials"
          % (ai.get("totalTriangleCount"), ai.get("totalVertexCount"),
             ai.get("drawCallCount"), ai.get("materialCount")))
    if ai.get("extensionsUsed"):
        A("extensions: used=%s required=%s"
          % (ai.get("extensionsUsed"), ai.get("extensionsRequired") or []))
    A("")
    A("errors %-4d  warnings %-4d  infos %-4d  hints %-4d"
      % (c["errors"], c["warnings"], c["infos"], c["hints"]))
    A("")

    if not summary["groups"]:
        A("  no issues reported.")
    for g in summary["groups"]:
        A("[%-7s] %-38s x%d" % (g["severity"], g["code"], g["count"]))
        A("          %s" % g["message"])
        for p in g["pointers"]:
            A("          at %s" % p)
        if g["count"] > len(g["pointers"]):
            A("          ... and %d more" % (g["count"] - len(g["pointers"])))
        if g["severity"] == "WARNING":
            j = str(allow.get(g["code"], "")).strip()
            A("          JUSTIFICATION: %s" % (j if j else "*** UNDOCUMENTED ***"))
        A("")

    A("-" * 78)
    A("VERDICT: %s" % ("PASS" if ok else "FAIL"))
    for r in (reasons or []):
        A("  - %s" % r)
    A("-" * 78)
    return "\n".join(L)


def validate(path, allow=None, strict=False, max_issues=0):
    """Convenience API for other pipeline stages. Returns (ok, summary, reasons)."""
    raw = run_validator(path, max_issues=max_issues)
    summary = structure(raw, path)
    ok, reasons = gate(summary, allow=allow, strict=strict)
    return ok, summary, reasons


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", nargs="+", help="GLB/glTF file(s) to validate")
    ap.add_argument("--strict", action="store_true",
                    help="also fail on any WARNING lacking a justification in --allow")
    ap.add_argument("--allow", help="JSON file: {code: justification}")
    ap.add_argument("--json", help="write the structured summary here")
    ap.add_argument("--raw-json", help="write the untouched Khronos report here")
    ap.add_argument("--max-issues", type=int, default=0,
                    help="cap reported issues (0 = unlimited, the default)")
    ap.add_argument("--quiet", action="store_true", help="suppress the text report")
    args = ap.parse_args()

    allow = {}
    if args.allow:
        if not os.path.exists(args.allow):
            print("FATAL: --allow file not found: %s" % args.allow, file=sys.stderr)
            return 2
        with open(args.allow) as fh:
            allow = json.load(fh)

    all_ok = True
    out = []
    for path in args.glb:
        try:
            raw = run_validator(path, max_issues=args.max_issues)
        except ValidatorUnavailable as e:
            # NOT TESTED is a distinct outcome from FAILED. Say so plainly.
            print("NOT TESTED: %s -- %s" % (path, e), file=sys.stderr)
            all_ok = False
            out.append({"file": path, "status": "NOT_TESTED", "reason": str(e)})
            continue

        summary = structure(raw, path)
        ok, reasons = gate(summary, allow=allow, strict=args.strict)
        summary["verdict"] = "PASS" if ok else "FAIL"
        summary["reasons"] = reasons
        all_ok = all_ok and ok
        out.append(summary)

        if not args.quiet:
            print(render(summary, allow=allow, reasons=reasons, ok=ok))
        if args.raw_json:
            with open(args.raw_json, "w") as fh:
                json.dump(raw, fh, indent=2)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(out if len(out) > 1 else out[0], fh, indent=2)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

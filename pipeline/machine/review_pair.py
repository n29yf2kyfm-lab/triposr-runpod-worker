#!/usr/bin/env python3
"""review_pair.py — the standing reviewer COUNCIL for a PRODUCTION CLAIM.

OWNER RULE 2026-08-26: no production claim ships on my own say-so. Fable 5 and
ox review it first. This is the SAME pair that wrote PRESERVE_PLAN.md — it is
deliberately not a new reviewer, because that plan's value came from ox
disagreeing with a draft I already believed was right (it killed a
factor-multiply respray design and caught a planarity guard that quietly
reinstated a rejected artefact).

WHY A MODULE. The pair has been assembled by hand for each review so far, which
means the evidence bundle differs every time and the verdicts are not
comparable. Here the bundle is fixed: the claim, the numbers behind it, and the
sheets. Reviews land in one JSON per claim so a later session can read what was
actually asked and answered.

THE TWO HALVES REACH THEIR MODEL DIFFERENTLY, and that is not an oversight:

  * ox   -- z-ai/glm-5.3-flash over OpenRouter, called here in-process via ox.py.
            Fully scriptable, so `--ox-only` is a complete run.
  * Fable 5 -- a Claude model, reached through the harness Agent tool, which a
            python process cannot call. So this module PREPARES Fable 5's
            bundle and records its verdict when handed back with --fable-verdict.
            Attempting to fake it from here would produce a review nobody ran.

COUNCIL OF THREE since 2026-08-26 (owner: "use as Council with ox"). Two
reviewers on one lab's model is one opinion counted twice, so the third runs a
DIFFERENT family:

  ox        z-ai/glm-5.3-flash   scriptable, in-process via ox.py
  Fable 5   Anthropic            via the harness Agent tool (manual hand-off)
  opencode  deepseek             scriptable, headless, READ-ONLY agent

The value is disagreement, and it showed on its first outing: on the hybrid van
run ox returned PASS and Fable 5 returned FAIL, and the FAIL was right -- it
found in the code that the glass channel could not fire on a van at all, which
ox had missed and I had reported as "unresolved".

A claim is DONE only when ALL THREE verdicts are recorded and none says FAIL.

Run:
  python3 review_pair.py --claim "van ships to bar" --evidence ev.json \\
      --image van_sheet.png --image yaris_sheet.png --out review_van.json
  python3 review_pair.py --out review_van.json --fable-verdict PASS \\
      --fable-notes "glass reads, tyres black, identity kept"
"""
import argparse
import json
import os
import subprocess
import tempfile
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# The bar, verbatim from the owner, 2026-08-26. Every review is scored against
# THIS text rather than a paraphrase, so two reviews of different claims are
# still asking the same question.
BAR = """The shipped STAGING GLB must have:
  1. real transparent glass with the interior visible THROUGH it -- proven from
     the shipped file, not forged by the render worker's material override
  2. tyres that read as black rubber
  3. identity kept: paint, badges, number plates, grille
  4. premium enough to ship: proportions right, lamps present, wheels right,
     no fused clay shell
This holds for EVERY body style, cars AND vans."""


def ask_ox(claim, evidence, images, timeout=900):
    """Call ox via ox.py. Returns (verdict_text, error_or_None)."""
    prompt = (f"You are reviewing a PRODUCTION CLAIM for a 3D car asset pipeline.\n\n"
              f"THE BAR:\n{BAR}\n\n"
              f"THE CLAIM:\n{claim}\n\n"
              f"MEASURED EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\n"
              "Answer, briefly and specifically, no praise:\n"
              "1. Does the evidence actually support the claim, or is a number "
              "standing in for something it does not measure?\n"
              "2. Which bar item is LEAST supported, and what would settle it?\n"
              "3. Anything in the images that contradicts the claim.\n"
              "4. Verdict: PASS or FAIL, one line why.")
    cmd = [sys.executable, os.path.join(HERE, "ox.py")]
    for im in images or []:
        cmd += ["--image", im]
    cmd.append(prompt)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "").strip()
        if not out:
            return None, f"ox returned nothing (rc={r.returncode}): {(r.stderr or '')[:300]}"
        return out, None
    except subprocess.TimeoutExpired:
        return None, f"ox timed out after {timeout}s"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def ask_opencode(claim, evidence, images, timeout=900):
    """Third reviewer: OpenCode, run headless on a DIFFERENT model family.

    WHY A THIRD, AND WHY DEEPSEEK. Two reviewers running the same lab's model
    is one opinion counted twice. ox is z-ai/glm-5.3-flash and Fable 5 is
    Anthropic, so this one is deliberately deepseek -- the disagreement is the
    product. It earned its place immediately: on the hybrid run ox returned
    PASS and Fable 5 returned FAIL, and the FAIL was correct.

    READ-ONLY BY CONSTRUCTION. OpenCode's default `build` agent carries
    `permission: * allow` -- full write and bash -- which is the wrong thing to
    point at a repo holding five live credentials. `--agent plan` is the
    read-only agent and `--pure` disables external plugins. A reviewer that can
    edit what it is reviewing is not a reviewer.

    Unlike Fable 5 this half IS scriptable, so a council run needs only the one
    manual hand-off.
    """
    # OPENCODE IS AN AGENT, NOT A CHAT ENDPOINT, and that bit twice: given file
    # paths and a repo to stand in, it went EXPLORING (`ls -la /tmp/gr/`) and
    # never produced a verdict, burning its whole budget. Three fences, all of
    # them because of that:
    #   1. NEVER list file paths. The old prompt ended with "SHEETS: <paths>",
    #      which is an invitation to go and read them. Images are described in
    #      the evidence by the caller instead.
    #   2. Say plainly it must not read or run anything.
    #   3. Run it in a NEUTRAL EMPTY cwd, not the repo -- if there is nothing
    #      to explore, exploring cannot eat the budget. This also keeps a
    #      reviewer away from a tree holding five live credentials.
    prompt = (f"You are the THIRD reviewer on a PRODUCTION CLAIM. The other two are "
              f"ox (z-ai/glm-5.3-flash) and Fable 5 (Anthropic). You are a different "
              f"model family from both -- do NOT defer to either.\n\n"
              "ANSWER FROM THE TEXT BELOW ONLY. Do not read files, do not list "
              "directories, do not run commands -- everything you need is here, and "
              "a review that spends its budget exploring returns nothing.\n\n"
              f"THE BAR:\n{BAR}\n\nTHE CLAIM:\n{claim}\n\n"
              f"MEASURED EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\n"
              "House rules: a number standing in for something it does not measure is "
              "the commonest failure here; a gate never observed to fail has not been "
              "tested; an average hides the tail; the render arbitrates over any "
              "metric; 'proven' must mean observed, not inferred.\n\n"
              "Answer briefly, no praise: 1) is any number doing work it cannot? "
              "2) which bar item is least supported and what would settle it? "
              "3) anything that contradicts the claim. "
              "Then a FINAL LINE of exactly: Verdict: PASS   or   Verdict: FAIL")
    oc = os.path.expanduser("~/.opencode/bin/opencode")
    if not os.path.exists(oc):
        return None, ("opencode not installed (~/.opencode/bin/opencode) — it is a "
                      "MACHINE-LOCAL install and does not survive a container "
                      "rollback; reinstall via .claude/hooks/session-start.sh")
    cmd = [oc, "run", "--pure", "--agent", "plan",
           "-m", os.environ.get("COUNCIL_MODEL",
                                "openrouter/~deepseek/deepseek-v4-flash-latest"),
           prompt]
    try:
        neutral = tempfile.mkdtemp(prefix="council-")      # nothing here to explore
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=neutral)
        out = (r.stdout or "").strip()
        if not out:
            return None, f"opencode returned nothing (rc={r.returncode}): {(r.stderr or '')[:300]}"
        # DISTINGUISH "explored instead of judging" FROM "no output at all".
        # Recording shell transcript as a review would put a non-review in the
        # council record, which is worse than a missing reviewer.
        if "verdict" not in out.lower():
            return None, ("opencode produced output but NO VERDICT — it explored "
                          f"instead of judging. tail: {out[-200:]}")
        return out, None
    except subprocess.TimeoutExpired:
        return None, f"opencode timed out after {timeout}s"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fable_bundle(claim, evidence, images):
    """The prompt to hand Fable 5 through the harness Agent tool.

    Returned rather than sent: a python process cannot call the Agent tool, and
    a module that pretended otherwise would record a review nobody ran.
    """
    return (f"You are the second reviewer on a PRODUCTION CLAIM. The other "
            f"reviewer is ox (z-ai/glm-5.3-flash). Do not defer to it.\n\n"
            f"THE BAR:\n{BAR}\n\n"
            f"THE CLAIM:\n{claim}\n\n"
            f"MEASURED EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\n"
            f"SHEETS: {', '.join(images or []) or '(none)'}\n\n"
            "Look at the sheets. Answer: which bar item is least supported; "
            "anything in the images that contradicts the claim; then "
            "Verdict: PASS or FAIL with one line why.")


def load(path):
    if path and os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim")
    ap.add_argument("--evidence", help="JSON file of measured numbers")
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--ox-only", action="store_true")
    ap.add_argument("--fable-verdict", choices=["PASS", "FAIL"])
    ap.add_argument("--fable-notes", default="")
    a = ap.parse_args()

    rec = load(a.out)

    # Recording Fable 5's verdict is a separate invocation, because it comes
    # back from the Agent tool after this process has already exited.
    if a.fable_verdict:
        rec.setdefault("reviews", {})["fable5"] = {
            "verdict": a.fable_verdict, "notes": a.fable_notes,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    else:
        if not a.claim:
            sys.exit("--claim required unless recording --fable-verdict")
        ev = load(a.evidence)
        rec.update({"claim": a.claim, "bar": BAR, "evidence": ev,
                    "images": a.image,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        txt, err = ask_ox(a.claim, ev, a.image)
        rec.setdefault("reviews", {})["ox"] = (
            {"verdict_text": txt} if txt else {"error": err})
        print("ox:", "OK" if txt else f"FAILED — {err}")
        if not a.ox_only:
            otxt, oerr = ask_opencode(a.claim, ev, a.image)
            rec.setdefault("reviews", {})["opencode"] = (
                {"verdict_text": otxt} if otxt else {"error": oerr})
            print("opencode:", "OK" if otxt else f"FAILED — {oerr}")
        if not a.ox_only:
            rec["fable5_bundle"] = fable_bundle(a.claim, ev, a.image)
            print("\n--- hand this to Fable 5 via the Agent tool, then re-run "
                  "with --fable-verdict ---")

    # A claim is DONE only when BOTH verdicts exist and neither failed.
    rv = rec.get("reviews", {})
    ox_txt = (rv.get("ox") or {}).get("verdict_text") or ""
    ox_pass = "PASS" in ox_txt.upper().split("VERDICT")[-1][:120] if ox_txt else None
    fb = (rv.get("fable5") or {}).get("verdict")
    oc_txt = (rv.get("opencode") or {}).get("verdict_text") or ""
    oc_pass = "PASS" in oc_txt.upper().split("VERDICT")[-1][:120] if oc_txt else None
    rec["both_reviewed"] = bool(ox_txt) and bool(fb) and bool(oc_txt)
    rec["claim_status"] = ("DONE" if (rec["both_reviewed"] and fb == "PASS"
                                      and ox_pass is not False
                                      and oc_pass is not False) else "NOT DONE")
    json.dump(rec, open(a.out, "w"), indent=1)
    print(f"\nwrote {a.out}  ox={'yes' if ox_txt else 'NO'} "
          f"fable5={fb or 'NOT YET'} opencode={'yes' if oc_txt else 'NO'}"
          f"  -> {rec['claim_status']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""ox.py — ask `z-ai/glm-5.3-flash` on OpenRouter, from the command line.

MODEL CHANGED 2026-08-26. `stealth/ox-alpha` now returns HTTP 404: its testing
period ended and OpenRouter's error body names the successor -- it WAS ZAI's
GLM-5.3 Flash, published as `z-ai/glm-5.3-flash`. Same model, stable id. It is
still a REASONING model (a two-token answer spent 28 reasoning tokens), so the
20000 max_tokens default below still matters: too small a budget lets reasoning
eat the whole allowance and return content=None, which looks like a broken call
and is not.

NOTE it is no longer free -- metered at ~$9e-06 for a trivial call. Cheap, but
not zero, so it is now a cost line rather than a freebie.

WHY A FILE AND NOT A ONE-LINER. This has been re-typed as a throwaway script
three times and lost to a container rollback each time, and two of its failure
modes look exactly like a broken model rather than a caller mistake.

  * OX-ALPHA IS A REASONING MODEL. The reply carries BOTH `message.reasoning`
    and `message.content`, and the reasoning is billed against the SAME
    `max_tokens` budget. Ask for 2000 and the reasoning eats all of it, the call
    returns HTTP 200 with `finish_reason: stop`, and `content` is None -- which
    reads as "the model returned nothing" and is really "you did not give it
    room to answer". Default here is 20000, and a None content is reported as
    that diagnosis rather than printed as an empty string.
  * THE KEY LIVES IN ~/.alam3d_env, never in the repo, and this file loads it
    itself. CLAUDE.md records a relaunch that forgot to source the env file and
    died one line in, in a way indistinguishable from a healthy start.

Free on the current key (a test call returned `cost: 0`), but the usage line is
printed after every call so that stops being an assumption.

UNION ALPHA (added 2026-09-17, owner request "connect to union alpha").
`stealth/union-alpha` is the current stealth slot -- the same kind of listing
ox-alpha occupied before it was unmasked as GLM-5.3 Flash. VERIFIED against
OpenRouter's own model list rather than the marketing post: 444 models
returned, exactly one match, `context_length` 262144 and BOTH `pricing.prompt`
and `pricing.completion` at 0. So it is genuinely free and genuinely 262K, and
it needs no code change at all:

    OX_MODEL=stealth/union-alpha python3 ox.py "question"

Two cautions carried over from ox-alpha, because a stealth slot behaves the
same way every time:
  * ASSUME IT IS A REASONING MODEL until measured otherwise -- keep the 20000
    max_tokens default, or a content=None reply will read as a broken model.
  * A STEALTH ID IS TEMPORARY. ox-alpha went 404 the day its testing window
    closed, and OpenRouter names the successor in the error body. When
    union-alpha 404s, read the body; do not assume the key broke.

Run:
    python3 ox.py "question"
    python3 ox.py --file prompt.txt
    python3 ox.py --image a.png --image b.png "what is wrong with these renders?"
    cat code.py | python3 ox.py --stdin --prefix "Review this:"
Env: OX_MODEL (z-ai/glm-5.3-flash; stealth/union-alpha for the free 262K slot)
     OX_MAX_TOKENS (20000) · OX_REASONING=1 to print the reasoning trace
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENV_FILE = "/root/.alam3d_env"
URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("OX_MODEL", "z-ai/glm-5.3-flash")

# ── FREE CHAIN ──────────────────────────────────────────────────────────
# The owner asked for a free-LLM router to cut spend. The tool doing the
# rounds (freellmapi) wants keys for 34 providers behind a gateway, and its
# own README says personal experimentation only. It is also forked so widely
# that a web search returns nine byte-identical repos under nine usernames,
# which is the supply-chain problem rather than a solution to it.
#
# None of that is needed. THE KEY WE ALREADY HOLD REACHES 25 GENUINELY FREE
# MODELS -- measured against OpenRouter's own model list, prompt AND
# completion both 0, of 446 total. The one good idea in the router is
# failover, and that is the twenty lines below.
#
# Measured on this key: nvidia/nemotron-3-ultra-550b-a55b:free answered a
# real technical question correctly at cost=0. A council review that cost
# $0.14 on unbiased/pareto costs nothing here.
#
# NOT EVERY ":free" MODEL IS REACHABLE. thinkingmachines/inkling:free returns
# HTTP 403 "only available on agentic harnesses" -- so the chain must skip a
# model that refuses rather than treating the refusal as the answer. That is
# what FREE_CHAIN plus the 403/429/5xx skip below is for.
#
#     OX_FREE=1 python3 ox.py "question"      # walk the free chain
#
# This does NOT reduce Claude Code's own usage -- that runs on Anthropic's
# API and no third-party gateway can route it. It reduces what THIS REPO
# spends on its own calls, which is the council reviews and the eye audits.
FREE_CHAIN = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",   # 550B, 1M ctx, verified cost 0
    "deepseek/deepseek-v4-flash-0731:free",     # 1M ctx
    "nvidia/nemotron-3.5-lightning:free",       # 1M ctx, fast
    "qwen/qwen3.8-27b:free",                    # 262K, vision
    "google/gemma-4-31b-it:free",               # 262K, vision
]
USE_FREE = os.environ.get("OX_FREE", "0") == "1"
MAX_TOKENS = int(os.environ.get("OX_MAX_TOKENS", "20000"))
SHOW_REASONING = os.environ.get("OX_REASONING", "0") == "1"


def load_key():
    """Read OPENROUTER_API_KEY ourselves. Never print it, never write it."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY=") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"REFUSED: OPENROUTER_API_KEY not in the environment or {ENV_FILE}")


def ask(prompt, model=MODEL, max_tokens=MAX_TOKENS, images=None):
    """images: local PNG/JPG paths, inlined as data URIs.

    ox-alpha's input modalities are text, image and video (checked against
    OpenRouter's own model list rather than assumed), so a render can be handed
    to it directly instead of described second-hand -- which matters here,
    because every visual verdict in this project is supposed to come from
    looking at the thing."""
    key = load_key()
    if images:
        import base64
        import mimetypes
        parts = [{"type": "text", "text": prompt}]
        for path in images:
            mime = mimetypes.guess_type(path)[0] or "image/png"
            b64 = base64.b64encode(open(path, "rb").read()).decode()
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{mime};base64,{b64}"}})
        content = parts
    else:
        content = prompt
    body = {"model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens}
    for attempt in range(6):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         method="POST")
            req.add_header("Authorization", f"Bearer {key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 4xx is our mistake and will not fix itself by retrying -- EXCEPT
            # 429, which is not our mistake at all. ox-alpha sits behind a
            # SHARED upstream pool and returns
            #   "z-ai/glm-5.3-flash is temporarily rate-limited upstream"
            # with limit_source=upstream_provider_shared_pool. That is somebody
            # else's traffic, it clears on its own, and the first version of
            # this file exited on it immediately -- turning a wait into a
            # failed review. Retry 429 and 5xx; give 429 a longer backoff
            # because a shared pool does not clear in two seconds.
            detail = e.read().decode()[:400]
            if (e.code < 500 and e.code != 429) or attempt == 5:
                sys.exit(f"OpenRouter HTTP {e.code}: {detail}")
            wait = (15 * 2 ** attempt) if e.code == 429 else (2 ** attempt)
            print(f"HTTP {e.code}; retrying in {wait}s "
                  f"(attempt {attempt + 1}/6)", file=sys.stderr)
            time.sleep(wait)
        except Exception as e:
            if attempt == 5:
                sys.exit(f"OpenRouter call failed: {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)


def ask_free(prompt, max_tokens=MAX_TOKENS, images=None):
    """Walk FREE_CHAIN until one model answers, and say which one did.

    A free endpoint can refuse for reasons that are nothing to do with the
    prompt: OpenRouter gates some free models to agentic harnesses (HTTP 403),
    and a shared free pool rate-limits (429). ask() correctly EXITS on a 403,
    because for a single named model that is a real failure. Here it is not --
    it just means try the next one. So this catches the exit and moves on, and
    only gives up when the whole chain has refused.
    """
    last = None
    for m in FREE_CHAIN:
        print(f"[free] trying {m}", file=sys.stderr)
        try:
            return ask(prompt, model=m, max_tokens=max_tokens, images=images)
        except SystemExit as e:
            last = str(e)
            print(f"[free] {m} unavailable: {last[:120]}", file=sys.stderr)
    sys.exit(f"every model in FREE_CHAIN refused. last: {last}")


def main():
    args = sys.argv[1:]
    images = []
    while "--image" in args:
        i = args.index("--image")
        images.append(args[i + 1])
        del args[i:i + 2]
    prefix = ""
    if "--prefix" in args:
        i = args.index("--prefix")
        prefix = args[i + 1]
        del args[i:i + 2]
    if "--stdin" in args:
        args.remove("--stdin")
        prompt = sys.stdin.read()
    elif "--file" in args:
        i = args.index("--file")
        prompt = open(args[i + 1]).read()
        del args[i:i + 2]
    else:
        prompt = " ".join(args)
    if prefix:
        prompt = f"{prefix}\n\n{prompt}"
    if not prompt.strip():
        sys.exit("REFUSED: empty prompt")

    if USE_FREE:
        d = ask_free(prompt, images=images or None)
    else:
        d = ask(prompt, images=images or None)
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = msg.get("content")
    usage = d.get("usage") or {}
    print(f"--- {d.get('model')}  finish={ch.get('finish_reason')}  "
          f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} "
          f"cost={usage.get('cost')}", file=sys.stderr)
    if SHOW_REASONING and msg.get("reasoning"):
        print("--- reasoning ---", file=sys.stderr)
        print(msg["reasoning"], file=sys.stderr)
        print("--- answer ---", file=sys.stderr)
    if not content:
        sys.exit(
            "OX RETURNED NO CONTENT. This is almost always the budget, not the "
            f"model: ox-alpha bills its reasoning against max_tokens (currently "
            f"{MAX_TOKENS}) and returns 200 with finish_reason=stop when the "
            "reasoning consumes all of it. Raise OX_MAX_TOKENS and retry.")
    print(content)


if __name__ == "__main__":
    main()

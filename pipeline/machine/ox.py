#!/usr/bin/env python3
"""ox.py — ask `stealth/ox-alpha` on OpenRouter, from the command line.

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

Run:
    python3 ox.py "question"
    python3 ox.py --file prompt.txt
    cat code.py | python3 ox.py --stdin --prefix "Review this:"
Env: OX_MODEL (stealth/ox-alpha) · OX_MAX_TOKENS (20000) · OX_REASONING=1 to
     also print the model's reasoning trace
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENV_FILE = "/root/.alam3d_env"
URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("OX_MODEL", "stealth/ox-alpha")
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


def ask(prompt, model=MODEL, max_tokens=MAX_TOKENS):
    key = load_key()
    body = {"model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens}
    for attempt in range(4):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         method="POST")
            req.add_header("Authorization", f"Bearer {key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 4xx is our mistake and will not fix itself by retrying
            detail = e.read().decode()[:400]
            if e.code < 500 or attempt == 3:
                sys.exit(f"OpenRouter HTTP {e.code}: {detail}")
            time.sleep(2 ** attempt)
        except Exception as e:
            if attempt == 3:
                sys.exit(f"OpenRouter call failed: {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)


def main():
    args = sys.argv[1:]
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

    d = ask(prompt)
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

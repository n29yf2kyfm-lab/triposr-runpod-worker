"""brief.py: one review batch made ready for an agent: its sheets (with a
checked item mixed into each) and its instructions filled in, so nothing is
edited by hand between batches.

    python3 brief.py build  NAME KEY ... [--per 8]  [--gold 1]
    python3 brief.py side   NAME KEY ... [--per 12] [--gold 1]
    python3 brief.py colour NAME KEY ... [--per 12] [--gold 1]
    python3 brief.py photo  NAME KEY ... [--per 12]
    (KEY ... may be @file: one key a line)

Writes F1K_HOME/sheets/NAME_sNN.jpg and F1K_HOME/sheets/NAME.md, and prints
the one line to give the agent.
"""
import os
import sys

import build_review
import paint_label
import paths
import web_photo

PROMPT = {"build": "build_review.md", "side": "side_label.md", "colour": "colour_label.md", "photo": "photo_review.md"}
PER = {"build": 8, "side": 12, "colour": 12, "photo": 12}


def keys_of(args):
    out = []
    for a in args:
        if a.startswith("@"):
            out += [l.strip() for l in open(a[1:]) if l.strip()]
        else:
            out.append(a)
    return out


def brief(kind, name, keys, per=None, n_gold=1):
    rows = paths.rows()[0]
    missing = [k for k in keys if k not in rows]
    if missing:
        raise SystemExit(f"no such keys: {missing[:5]}")
    if kind in ("build",):
        keys = [k for k in keys if rows[k].get("status") in ("built", "standin")]
    per = per or PER[kind]
    d = paths.f("sheets")
    os.makedirs(d, exist_ok=True)
    sheets = []
    for i in range(0, len(keys), per):
        out = os.path.join(d, f"{name}_s{i // per:02d}.jpg")
        chunk = keys[i:i + per]
        if kind == "build":
            build_review.sheet(out, chunk, name, n_gold)
        elif kind == "side":
            paint_label.sheet(out, chunk, name, n_gold, kind="side", ask="name the way each car points")
        elif kind == "colour":
            paint_label.sheet(out, chunk, name, n_gold, kind="paint")
        else:
            web_photo.sheet(out, chunk)
        sheets.append(out)
    # the batch's own keys, kept away from the sheets: an agent that found them
    # could tell the checked items on its sheets from its own
    runs = paths.f("review_runs")
    os.makedirs(runs, exist_ok=True)
    with open(os.path.join(runs, f"{name}.keys"), "w") as fh:
        fh.write("\n".join(keys) + "\n")
    text = open(os.path.join(paths.REVIEW, "prompts", PROMPT[kind])).read()
    sheet_list = f"{len(sheets)} sheets, {sheets[0]} to {sheets[-1]}" if len(sheets) > 1 else sheets[0]
    text = text.replace("{REPO}", paths.REPO).replace("{F1K_HOME}", paths.home()).replace("{SHEETS}", sheet_list) \
        .replace("{BATCH}", name)
    md = os.path.join(d, f"{name}.md")
    with open(md, "w") as fh:
        fh.write(text)
    print(f"{len(keys)} keys on {len(sheets)} sheets")
    print(f"Give the agent: Read {md} first and follow it exactly; your batch is {name}; look at every sheet "
          f"and answer every item on it; end with the short FINAL REPORT it asks for.")
    return md


def main():
    a = sys.argv[1:]
    if len(a) < 3 or a[0] not in PROMPT:
        raise SystemExit(__doc__)
    per = int(a[a.index("--per") + 1]) if "--per" in a else None
    n_gold = int(a[a.index("--gold") + 1]) if "--gold" in a else (0 if a[0] == "photo" else 1)
    rest = [x for i, x in enumerate(a[2:], 2) if not x.startswith("--") and a[i - 1] not in ("--per", "--gold")]
    brief(a[0], a[1], keys_of(rest), per, n_gold)


if __name__ == "__main__":
    main()

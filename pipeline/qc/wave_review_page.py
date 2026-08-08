#!/usr/bin/env python3
"""wave_review_page.py — build the numbered eye-review page for a sourcing wave.

The owner's quality gate is a human looking at contact sheets and calling out
numbers (see CLAUDE.md, "Quality-gate standard"). This produces the surface that
review happens on: every sheet in the wave, numbered 1..N, with the material
figures beside it and an index mapping each number back to its uid.

Two things it deliberately does NOT do:

  * it does not rank or pre-judge the cars. The green/amber split shown is the
    `mat_audit` result only — a mechanical test of whether a colour swap would
    land on bodywork. A car can be amber and excellent, or green and junk. Saying
    otherwise on the page would put a thumb on the scale of the owner's review.
  * it does not drop the suspect half. They are ordered near-misses first and
    shown at the same size, because an amber car the owner wants can still ship
    without recolour.

Both themes keep the image well at a constant near-black mat. Judging paint and
reflections against a surround that changes with the viewer's OS setting is not
a fair comparison, so the chrome adapts and the viewing condition does not.

Input is the wave triage JSON: a list of objects carrying at least
`uid`, `name`, `mats`, `cov`, `klass` ("clean" | "suspect"), and optionally
`faces`, `author`, `licence`, `i`.

Usage:
    wave_review_page.py --triage /tmp/seat/triage.json --marque SEAT \
        --prefix audit/seat --out /tmp/seat/review.html [--quality 74]
"""
import argparse, base64, html, io, json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

ENV_FILE = "/root/.alam3d_env"
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-meshes"
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets")


def load_env(path=ENV_FILE):
    """Load creds ourselves. A relaunch that forgot to source the env file once
    died one line in and the failure looked exactly like a healthy start."""
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()


def esc(s):
    return html.escape(str(s))


def fetch(prefix, uid, dest):
    p = os.path.join(dest, uid + ".jpg")
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return "skip"
    for attempt in range(4):
        try:
            d = urllib.request.urlopen(f"{SB}/{prefix}/{uid}.jpg", timeout=120).read()
            open(p, "wb").write(d)
            return "ok"
        except Exception:
            continue
    return "fail"


def compress(src, quality):
    """Shrink for embedding but keep native width — the reviewer is looking for
    grille depth and shut lines, and a downscale destroys exactly that."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue(), im.size


def why(r):
    """State what the audit measured. No adjectives about the car itself."""
    m, c = r["mats"], r["cov"]
    if r["klass"] == "clean":
        return (f"{m} body material{'s' if m != 1 else ''}, {c:.0%} of the mesh"
                " — inside the paintable band.")
    bits = []
    if c >= 0.95:
        bits.append(f"body share {c:.0%} — effectively the whole mesh is one material, so a "
                    "colour swap would paint glass, lights and rims too")
    elif c > 0.45:
        bits.append(f"body share {c:.0%}, above the 45% ceiling — paint would spill onto "
                    "trim or wheels")
    elif c < 0.05:
        bits.append(f"body share {c:.0%}, below the 5% floor — almost nothing to paint")
    if m > 2:
        bits.append(f"{m} materials classed as body (the limit is 2)")
    elif m == 0:
        bits.append("no material the audit could class as body")
    return ("; ".join(bits) or "outside the paintable band").capitalize() + "."


CSS = """
@font-face{font-family:"Cond";src:url(data:font/woff2;base64,__FR__) format("woff2");font-weight:400;font-display:swap}
@font-face{font-family:"Cond";src:url(data:font/woff2;base64,__FB__) format("woff2");font-weight:700;font-display:swap}
:root{
  --ground:#e8eaee; --surface:#fff; --sunk:#f1f3f6;
  --ink:#141920; --ink-2:#3d4753; --muted:#6a7480; --line:#d2d7de;
  --accent:#a8402f; --clean:#2b6f52; --clean-bg:#dcece4;
  --susp:#8a6410; --susp-bg:#f5ead1; --mat:#0d0f12;
  --display:"Cond","DejaVu Sans Condensed","Liberation Sans Narrow",system-ui,sans-serif;
  --body:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"DejaVu Sans Mono",monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0f1216; --surface:#171b21; --sunk:#12161b;
  --ink:#e5e9ee; --ink-2:#b7c0ca; --muted:#87919d; --line:#282f38;
  --accent:#e0705c; --clean:#5cbb92; --clean-bg:#16302566;
  --susp:#d8a93f; --susp-bg:#33280f;
}}
:root[data-theme="dark"]{
  --ground:#0f1216; --surface:#171b21; --sunk:#12161b;
  --ink:#e5e9ee; --ink-2:#b7c0ca; --muted:#87919d; --line:#282f38;
  --accent:#e0705c; --clean:#5cbb92; --clean-bg:#16302566;
  --susp:#d8a93f; --susp-bg:#33280f;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--body);
  font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}
.num{font-variant-numeric:tabular-nums}
h1,h2{font-family:var(--display);font-weight:700;margin:0;line-height:1.1;text-wrap:balance}
p{margin:0}
code{font-family:var(--mono);font-size:11px;color:var(--muted);word-break:break-all}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1560px;margin:0 auto;padding:0 20px}
.bar{position:sticky;top:0;z-index:20;background:var(--surface);border-bottom:1px solid var(--line)}
.bar__in{display:flex;flex-wrap:wrap;align-items:center;gap:10px 22px;padding:11px 0}
.bar h1{font-size:20px;text-transform:uppercase;letter-spacing:.05em}
.bar__counts{display:flex;gap:8px;margin-right:auto}
.tally{font-family:var(--display);font-size:12px;text-transform:uppercase;
  letter-spacing:.09em;padding:3px 9px;border:1px solid currentColor}
.tally--clean{color:var(--clean);background:var(--clean-bg)}
.tally--susp{color:var(--susp);background:var(--susp-bg)}
.tally--all{color:var(--muted)}
.idx{background:var(--sunk);border-bottom:1px solid var(--line)}
.idx__in{padding:14px 0 16px;display:flex;flex-direction:column;gap:9px}
.idx__lab{font-family:var(--display);font-size:11px;text-transform:uppercase;
  letter-spacing:.12em;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.chip{font-family:var(--display);font-weight:700;font-size:13px;min-width:28px;height:28px;
  display:inline-flex;align-items:center;justify-content:center;text-decoration:none;
  border:1px solid;font-variant-numeric:tabular-nums;padding:0 5px}
.chip--clean{color:var(--clean);border-color:var(--clean);background:var(--clean-bg)}
.chip--suspect{color:var(--susp);border-color:var(--susp);background:var(--susp-bg)}
.chip:hover{filter:brightness(1.12)}
.intro{padding:26px 0 6px;display:flex;flex-direction:column;gap:12px;max-width:74ch}
.intro p{color:var(--ink-2)}
.intro strong{color:var(--ink)}
.sect{padding-top:36px}
.sect__hd{display:flex;align-items:baseline;gap:14px;padding:10px 0 6px;
  border-bottom:2px solid var(--line);margin-bottom:20px;position:sticky;top:49px;
  background:var(--ground);z-index:10}
.sect__hd h2{font-size:23px;text-transform:uppercase;letter-spacing:.04em}
.sect__hd p{font-size:14px;color:var(--muted)}
.car{background:var(--surface);border:1px solid var(--line);margin-bottom:22px;
  scroll-margin-top:96px}
.car__hd{display:flex;align-items:flex-start;gap:16px;padding:13px 16px}
.car__n{font-family:var(--display);font-weight:700;font-size:30px;line-height:1;
  color:var(--accent);min-width:44px}
.car__id{flex:1;min-width:0}
.car__id h2{font-size:21px}
.by{font-size:13px;color:var(--muted)}
.pill{font-family:var(--display);font-size:11px;text-transform:uppercase;
  letter-spacing:.1em;padding:3px 9px;border:1px solid currentColor;white-space:nowrap}
.pill--clean{color:var(--clean);background:var(--clean-bg)}
.pill--suspect{color:var(--susp);background:var(--susp-bg)}
.well{background:var(--mat);border-block:1px solid var(--line)}
.well img{width:100%;height:auto;display:block}
.car__ft{padding:12px 16px 14px;display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 26px}
.car__ft dl{display:flex;gap:22px;margin:0}
.car__ft dl div{display:flex;flex-direction:column}
.car__ft dt{font-family:var(--display);font-size:10px;text-transform:uppercase;
  letter-spacing:.11em;color:var(--muted)}
.car__ft dd{margin:0;font-size:15px;color:var(--ink-2)}
.why{flex:1;min-width:260px;font-size:14px;color:var(--ink-2)}
.rubric{background:var(--sunk);border:1px solid var(--line);padding:16px 20px;
  display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px 30px;
  margin-top:20px}
.rubric h3{font-family:var(--display);font-size:12px;text-transform:uppercase;
  letter-spacing:.11em;margin:0 0 6px}
.rubric ul{margin:0;padding-left:18px;font-size:14px;color:var(--ink-2)}
.rubric li{padding:1px 0}
.rubric--pass h3{color:var(--clean)}
.rubric--fail h3{color:var(--accent)}
details{margin:30px 0 40px;background:var(--surface);border:1px solid var(--line)}
summary{cursor:pointer;padding:12px 16px;font-family:var(--display);font-weight:700;
  text-transform:uppercase;letter-spacing:.1em;font-size:12px}
pre{margin:0;padding:0 16px 16px;overflow-x:auto;font-family:var(--mono);font-size:12px;
  color:var(--ink-2);line-height:1.65}
footer{border-top:1px solid var(--line);background:var(--surface);padding:22px 0 40px;
  color:var(--muted);font-size:14px}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage", required=True)
    ap.add_argument("--marque", required=True)
    ap.add_argument("--prefix", required=True, help="bucket prefix, e.g. audit/seat")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="", help="local sheet cache dir")
    ap.add_argument("--quality", type=int, default=74)
    ap.add_argument("--swept", type=int, default=0, help="candidates swept, for the intro")
    ap.add_argument("--note", default="", help="extra sentence for the intro")
    a = ap.parse_args()

    rows = json.load(open(a.triage))
    cache = a.cache or os.path.join(os.path.dirname(a.out), "sheets")
    os.makedirs(cache, exist_ok=True)

    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda r: fetch(a.prefix, r["uid"], cache), rows))
    if "fail" in got:
        bad = [r["uid"] for r, g in zip(rows, got) if g == "fail"]
        sys.exit(f"could not fetch {len(bad)} sheets: {bad[:3]}")

    clean = sorted([r for r in rows if r["klass"] == "clean"], key=lambda r: r["cov"])
    susp = sorted([r for r in rows if r["klass"] == "suspect"], key=lambda r: r["cov"])
    ordered = clean + susp
    for n, r in enumerate(ordered, 1):
        r["n"] = n

    def card(r):
        data, (w, h) = compress(os.path.join(cache, r["uid"] + ".jpg"), a.quality)
        src = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        meta = []
        if r.get("faces"):
            meta.append(f'<div><dt>Faces</dt><dd class="num">{r["faces"]:,}</dd></div>')
        meta.append(f'<div><dt>Body mats</dt><dd class="num">{r["mats"]}</dd></div>')
        meta.append(f'<div><dt>Body share</dt><dd class="num">{r["cov"]:.3f}</dd></div>')
        by = " · ".join(x for x in (r.get("author"), r.get("licence"),
                                    f"row {r['i']} of the sweep" if r.get("i") else "") if x)
        return f'''<article class="car" id="c{r['n']}">
  <header class="car__hd">
    <span class="car__n num">{r['n']}</span>
    <div class="car__id"><h2>{esc(r['name'])}</h2><p class="by">{esc(by)}</p></div>
    <span class="pill pill--{r['klass']}">{r['klass']}</span>
  </header>
  <div class="well"><img src="{src}" alt="Four-view studio sheet — {esc(r['name'])}"
       width="{w}" height="{h}" loading="lazy" decoding="async"></div>
  <footer class="car__ft"><dl>{''.join(meta)}</dl>
    <p class="why">{esc(why(r))}</p><code>{esc(r['uid'])}</code></footer>
</article>'''

    chips = "".join(f'<a class="chip chip--{r["klass"]}" href="#c{r["n"]}" '
                    f'title="{esc(r["name"])}">{r["n"]}</a>' for r in ordered)
    index_txt = "\n".join(
        f"#{r['n']:<3} {r['uid']}  {r['klass']:<7} mats={r['mats']} cov={r['cov']:.3f}  {r['name']}"
        for r in ordered)

    css = CSS.replace("__FR__", base64.b64encode(
        open(os.path.join(FONT_DIR, "DejaVuSansCondensed.woff2"), "rb").read()).decode()
    ).replace("__FB__", base64.b64encode(
        open(os.path.join(FONT_DIR, "DejaVuSansCondensed-Bold.woff2"), "rb").read()).decode())

    swept = (f"<strong>{a.swept} {esc(a.marque)} candidates were swept; "
             f"{len(rows)} rendered.</strong> ") if a.swept else \
            f"<strong>{len(rows)} {esc(a.marque)} sheets.</strong> "

    doc = f'''<title>{esc(a.marque)} sourcing wave — {len(rows)} sheets for review</title>
<style>{css}</style>
<div class="bar"><div class="wrap bar__in">
  <h1>{esc(a.marque)} wave</h1>
  <div class="bar__counts">
    <span class="tally tally--all">{len(rows)} sheets</span>
    <span class="tally tally--clean">{len(clean)} clean split</span>
    <span class="tally tally--susp">{len(susp)} suspect</span>
  </div>
  <a href="#clean">Clean</a><a href="#suspect">Suspect</a><a href="#index">Index</a>
</div></div>
<div class="idx"><div class="wrap idx__in">
  <span class="idx__lab">Jump to a car — green passed the material split, amber did not</span>
  <div class="chips">{chips}</div>
</div></div>
<main class="wrap">
  <div class="intro">
    <p>{swept}Every one below is a four-view sheet at the rubric angles — front
      three-quarter, front three-quarter from the left, side, rear three-quarter.
      Nothing here has been judged. The green/amber split is the <em>material audit</em>
      only, a mechanical test of whether a colour swap would land on the bodywork; it
      says nothing about whether the car is any good.</p>
    <p>Call out the numbers to scrap and they are quarantined reversibly — entry and
      assets kept, both Supabase paths re-served. An amber car you like is not lost: it
      ships without recolour, or gets its body material fixed first.{(" " + esc(a.note)) if a.note else ""}</p>
  </div>
  <div class="rubric">
    <div class="rubric--pass"><h3>Your pass bar</h3>
      <ul><li>proportions read as the right car instantly</li>
        <li>front three-quarter is strong</li>
        <li>roof, pillars, wheelbase consistent across all four views</li>
        <li>reflections clean</li><li>paint finish looks premium</li></ul></div>
    <div class="rubric--fail"><h3>Your fail bar</h3>
      <ul><li>grille edges soft, honeycomb shallow</li>
        <li>headlights lacking sharp internal LED elements</li>
        <li>wheel spokes inconsistent between views</li>
        <li>rear bumper and diffuser soft versus the real car</li>
        <li>door and bonnet shut lines not defined</li></ul></div>
  </div>
  <section class="sect" id="clean">
    <div class="sect__hd"><h2>Clean split</h2>
      <p>{len(clean)} cars · 1–2 body materials, 5–45% of the mesh · ordered by body share</p></div>
    {"".join(card(r) for r in clean)}
  </section>
  <section class="sect" id="suspect">
    <div class="sect__hd"><h2>Suspect split</h2>
      <p>{len(susp)} cars · outside the paintable band · ordered by body share, near-misses first</p></div>
    {"".join(card(r) for r in susp)}
  </section>
  <details id="index"><summary>Index — #N to uid</summary><pre>{esc(index_txt)}</pre></details>
</main>
<footer class="wrap"><p>Sheets stored at
  <code>car-meshes/{esc(a.prefix)}/&lt;uid&gt;.jpg</code>. Material figures come from
  <code>mat_audit</code> (<code>body_pct</code>), taken during the render wave.
  Licences are recorded as the source states them and are not a gate.</p></footer>
'''
    open(a.out, "w").write(doc)
    mb = os.path.getsize(a.out) / 1e6
    print(f"{len(rows)} sheets ({len(clean)} clean / {len(susp)} suspect) -> {a.out}  {mb:.2f} MB")
    if mb > 15:
        print("WARNING: over 15 MB; the artifact ceiling is 16 MB. Lower --quality.",
              file=sys.stderr)


if __name__ == "__main__":
    main()

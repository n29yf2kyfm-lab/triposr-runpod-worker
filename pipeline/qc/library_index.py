#!/usr/bin/env python3
"""library_index.py — the human-readable index of what is actually in the library.

The catalogue is a 1,300-entry JSON file. Nobody can inspect a reg-lookup
library by reading it, and the two questions that matter most are invisible in
it: *which* cars a DVLA decode can actually reach, and which of them ship the
eight colours. This builds one page that answers both, per marque.

It is a report, not a gate — it changes nothing and touches no network. It reads
whichever catalogue you point it at, so it can be run against the working copy
before a serve to see exactly what is about to go live.

Reachability note: `resolveVehicle` gates on make + modelFamily before it scores
anything, so an entry with no yearStart is still reachable but cannot be
year-discriminated against a sibling generation — that is why "no year" is shown
as a gap rather than a failure. bodyStyle is a HARD reject in scoreAsset when it
disagrees, but absent is fine; trim families only ever add score.

Usage:
  python3 pipeline/qc/library_index.py [--catalogue PATH] [--out PATH]
"""
import argparse, collections, datetime, html, json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The eight DVLA colour families every colour-swap car bakes. Order is fixed so
# the swatch strip reads the same on every row and a missing chip is obvious.
DVLA = [("white", "#F2F3F4"), ("silver", "#C3C7CC"), ("grey", "#7C838B"),
        ("black", "#23262A"), ("blue", "#2C5DA8"), ("red", "#B0302A"),
        ("green", "#2C6B47"), ("yellow", "#D9B02C")]

PRETTY = {"bmw": "BMW", "byd": "BYD", "mg": "MG", "ds": "DS", "gmc": "GMC",
          "mercedes-benz": "Mercedes-Benz", "land-rover": "Land Rover",
          "alfa-romeo": "Alfa Romeo", "aston-martin": "Aston Martin",
          "rolls-royce": "Rolls-Royce", "great-wall": "Great Wall",
          "seat": "SEAT", "mini": "MINI", "kgm": "KGM", "ssangyong": "SsangYong"}


def pretty(s):
    if not s:
        return ""
    if s in PRETTY:
        return PRETTY[s]
    return " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in s.split("-"))


def years(e):
    a, b = e.get("yearStart"), e.get("yearEnd")
    if a and b and a != b:
        return f"{a}–{b}"
    return str(a or b or "")


def build(cat):
    rows = []
    for e in cat:
        if e.get("publicationStatus") != "approved":
            continue
        cv = e.get("colourVariants") or {}
        stamp = (e.get("recolourAudit") or {}).get("status")
        rows.append({
            "make": e["make"], "model": e.get("model", ""),
            "aid": e["assetId"], "years": years(e),
            "body": e.get("bodyStyle") or "",
            "trims": e.get("compatibleTrimFamilies") or [],
            "colours": sorted(cv.keys()),
            "ncol": len(cv),
            "blocked": bool(e.get("colourSwapBlocked")),
            "stamp": stamp or "",
            "poster": bool(e.get("posterUrl")),
        })
    rows.sort(key=lambda r: (r["make"], r["model"].lower(), r["years"]))
    return rows


def render(rows, cat_path):
    n = len(rows)
    full8 = sum(1 for r in rows if r["ncol"] == 8)
    noyear = sum(1 for r in rows if not r["years"])
    notrim = sum(1 for r in rows if not r["trims"])
    nobody = sum(1 for r in rows if not r["body"])
    by_make = collections.OrderedDict()
    for r in rows:
        by_make.setdefault(r["make"], []).append(r)
    marques = sorted(by_make.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    built = datetime.datetime.now().strftime("%d %b %Y, %H:%M")

    def chips(r):
        out = []
        for name, hexv in DVLA:
            on = name in r["colours"]
            out.append(f'<i class="chip{"" if on else " off"}" style="--c:{hexv}" '
                       f'title="{name}{"" if on else " — not baked"}"></i>')
        return "".join(out)

    def status(r):
        if r["ncol"] == 8:
            return '<span class="pill ok">8 colours</span>'
        if r["blocked"]:
            return '<span class="pill blocked">single neutral</span>'
        if r["ncol"]:
            return f'<span class="pill part">{r["ncol"]} colours</span>'
        return '<span class="pill blocked">single neutral</span>'

    sections = []
    for make, rs in marques:
        f8 = sum(1 for r in rs if r["ncol"] == 8)
        trs = []
        for r in rs:
            gaps = []
            if not r["years"]:
                gaps.append("year")
            if not r["body"]:
                gaps.append("body")
            if not r["trims"]:
                gaps.append("trim")
            trim_txt = ", ".join(r["trims"]) if r["trims"] else '<span class="gap">—</span>'
            trs.append(
                f'<tr data-gaps="{" ".join(gaps)}">'
                f'<td class="model">{html.escape(pretty(r["model"]))}'
                f'<span class="aid">{html.escape(r["aid"])}</span></td>'
                f'<td class="num">{r["years"] or "<span class=gap>—</span>"}</td>'
                f'<td class="body">{html.escape(r["body"]) or "<span class=gap>—</span>"}</td>'
                f'<td class="trim">{trim_txt}</td>'
                f'<td class="sw">{chips(r)}</td>'
                f'<td class="st">{status(r)}</td></tr>')
        sections.append(f"""<section class="marque" data-make="{html.escape(make)}">
  <header class="mh"><h2>{html.escape(pretty(make))}</h2>
    <p class="mmeta"><b>{len(rs)}</b> cars &middot; <b>{f8}</b> with all eight colours</p></header>
  <div class="tw"><table>
    <thead><tr><th>Model</th><th class="num">Years</th><th>Body</th>
      <th>Trim families</th><th class="sw">Colours</th><th class="st">Status</th></tr></thead>
    <tbody>{"".join(trs)}</tbody>
  </table></div>
</section>""")

    return f"""<title>Car library index — {n} live models</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --ground:#F3F5F7; --surface:#FFFFFF; --line:#DEE3E9; --line-soft:#EDF0F4;
  --ink:#151A20; --ink-2:#4E5964; --ink-3:#78838F;
  --accent:#1F5F8B; --accent-soft:#E8F0F6;
  --ok:#2C7355; --ok-bg:#E4F1EA; --part:#8A6413; --part-bg:#F6EEDA;
  --blocked:#9C3A31; --blocked-bg:#F7E7E5;
  --chip-line:#C2C9D1;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#0F1216; --surface:#161B21; --line:#262D36; --line-soft:#1E242B;
    --ink:#E6EBF1; --ink-2:#A2AEBB; --ink-3:#77828F;
    --accent:#74AAD6; --accent-soft:#16222D;
    --ok:#7FC7A3; --ok-bg:#16261F; --part:#D9B366; --part-bg:#2A2417;
    --blocked:#E39289; --blocked-bg:#2B1B1A;
    --chip-line:#39424C;
  }}
}}
:root[data-theme="dark"] {{
  --ground:#0F1216; --surface:#161B21; --line:#262D36; --line-soft:#1E242B;
  --ink:#E6EBF1; --ink-2:#A2AEBB; --ink-3:#77828F;
  --accent:#74AAD6; --accent-soft:#16222D;
  --ok:#7FC7A3; --ok-bg:#16261F; --part:#D9B366; --part-bg:#2A2417;
  --blocked:#E39289; --blocked-bg:#2B1B1A;
  --chip-line:#39424C;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--ground); color:var(--ink);
  font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1180px; margin:0 auto; padding:40px 20px 80px; }}
h1 {{
  font-size:clamp(26px,4vw,38px); line-height:1.1; margin:0 0 6px;
  letter-spacing:-0.022em; font-weight:700; text-wrap:balance;
}}
.sub {{ color:var(--ink-2); margin:0 0 28px; font-size:15px; }}
.sub code {{ font:12px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; color:var(--ink-3); }}

.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:28px; }}
.stat {{ background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:14px 16px; }}
.stat b {{ display:block; font-size:27px; font-weight:700; letter-spacing:-0.02em;
  font-variant-numeric:tabular-nums; line-height:1.15; }}
.stat span {{ display:block; font-size:11px; letter-spacing:.07em; text-transform:uppercase;
  color:var(--ink-3); margin-top:3px; }}
.stat.flag b {{ color:var(--part); }}

.bar {{ position:sticky; top:0; z-index:5; display:flex; flex-wrap:wrap; gap:10px; align-items:center;
  background:var(--ground); padding:12px 0; margin-bottom:8px; border-bottom:1px solid var(--line); }}
.bar input {{ flex:1 1 240px; min-width:0; padding:9px 12px; font:inherit; font-size:14px;
  color:var(--ink); background:var(--surface); border:1px solid var(--line); border-radius:6px; }}
.bar input::placeholder {{ color:var(--ink-3); }}
.bar input:focus-visible, .bar button:focus-visible {{ outline:2px solid var(--accent); outline-offset:1px; }}
.bar button {{ font:inherit; font-size:13px; padding:8px 13px; cursor:pointer; border-radius:6px;
  color:var(--ink-2); background:var(--surface); border:1px solid var(--line); }}
.bar button[aria-pressed="true"] {{ color:var(--accent); background:var(--accent-soft); border-color:var(--accent); }}
.count {{ font-size:13px; color:var(--ink-3); font-variant-numeric:tabular-nums; margin-left:auto; }}

.marque {{ margin-top:34px; }}
.mh {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
  padding-bottom:8px; border-bottom:2px solid var(--ink); margin-bottom:0; }}
.mh h2 {{ font-size:19px; margin:0; letter-spacing:-0.01em; font-weight:700; }}
.mmeta {{ margin:0; font-size:12.5px; color:var(--ink-3); }}
.mmeta b {{ color:var(--ink-2); font-variant-numeric:tabular-nums; }}

.tw {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ text-align:left; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--ink-3); font-weight:600; padding:10px 10px 8px; white-space:nowrap; }}
td {{ padding:9px 10px; border-top:1px solid var(--line-soft); vertical-align:top; }}
tbody tr:hover td {{ background:var(--surface); }}
.model {{ font-weight:600; min-width:190px; }}
.aid {{ display:block; font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--ink-3); font-weight:400; margin-top:2px; word-break:break-all; }}
td.num {{ font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--ink-2); }}
th.num {{ text-align:left; }}
.body, .trim {{ color:var(--ink-2); }}
.trim {{ max-width:290px; font-size:13px; }}
.gap {{ color:var(--ink-3); }}

td.sw {{ white-space:nowrap; }}
.chip {{ display:inline-block; width:15px; height:15px; border-radius:50%;
  background:var(--c); border:1px solid var(--chip-line); margin-right:3px; vertical-align:middle; }}
.chip.off {{ background:transparent; border-style:dashed; }}

.pill {{ display:inline-block; font-size:11px; font-weight:600; letter-spacing:.02em;
  padding:3px 8px; border-radius:99px; white-space:nowrap; }}
.pill.ok {{ color:var(--ok); background:var(--ok-bg); }}
.pill.part {{ color:var(--part); background:var(--part-bg); }}
.pill.blocked {{ color:var(--blocked); background:var(--blocked-bg); }}

.foot {{ margin-top:44px; padding-top:16px; border-top:1px solid var(--line);
  font-size:12.5px; color:var(--ink-3); }}
.foot p {{ margin:0 0 7px; max-width:66ch; }}
@media (max-width:640px) {{ .wrap {{ padding:26px 14px 60px; }} .trim {{ max-width:180px; }} }}
</style>

<div class="wrap">
<h1>Car library index</h1>
<p class="sub">{n} approved models a UK registration can resolve to, across {len(marques)} marques.
Built {built} from <code>{html.escape(os.path.basename(cat_path))}</code>.</p>

<div class="stats">
  <div class="stat"><b>{n}</b><span>live models</span></div>
  <div class="stat"><b>{full8}</b><span>all eight colours</span></div>
  <div class="stat{" flag" if noyear else ""}"><b>{noyear}</b><span>no year</span></div>
  <div class="stat{" flag" if nobody else ""}"><b>{nobody}</b><span>no body style</span></div>
  <div class="stat{" flag" if notrim else ""}"><b>{notrim}</b><span>no trim families</span></div>
</div>

<div class="bar">
  <input id="q" type="search" placeholder="Filter by marque, model or asset id…" aria-label="Filter the library">
  <button id="f8" aria-pressed="false">Missing colours</button>
  <button id="fy" aria-pressed="false">Missing year</button>
  <button id="ft" aria-pressed="false">Missing trim</button>
  <span class="count" id="count"></span>
</div>

{"".join(sections)}

<div class="foot">
  <p><b>Colours.</b> Each row shows the eight DVLA colour families baked for that car.
  A dashed ring is a colour that is not baked. "Single neutral" means the colour swap was
  audited and did not move the body colour, so the car ships in one colour rather than
  eight near-identical files.</p>
  <p><b>Gaps.</b> A missing year or trim does not make a car unreachable — the resolver
  matches on make and model family first. It means the car cannot be told apart from a
  sibling generation when a decode names a year, so the gaps above are ranked work, not
  faults.</p>
</div>
</div>

<script>
(function () {{
  var rows = Array.prototype.slice.call(document.querySelectorAll('tbody tr'));
  var secs = Array.prototype.slice.call(document.querySelectorAll('.marque'));
  var q = document.getElementById('q'), count = document.getElementById('count');
  var btn = {{ f8: document.getElementById('f8'), fy: document.getElementById('fy'),
              ft: document.getElementById('ft') }};
  var on = {{ f8: false, fy: false, ft: false }};

  function apply() {{
    var term = q.value.trim().toLowerCase();
    var shown = 0;
    rows.forEach(function (tr) {{
      var gaps = tr.dataset.gaps || '';
      var ok = true;
      if (term && tr.textContent.toLowerCase().indexOf(term) === -1) ok = false;
      if (ok && on.f8 && tr.querySelectorAll('.chip.off').length === 0) ok = false;
      if (ok && on.fy && gaps.indexOf('year') === -1) ok = false;
      if (ok && on.ft && gaps.indexOf('trim') === -1) ok = false;
      tr.hidden = !ok;
      if (ok) shown++;
    }});
    secs.forEach(function (s) {{
      s.hidden = s.querySelectorAll('tbody tr:not([hidden])').length === 0;
    }});
    count.textContent = shown + ' of {n} shown';
  }}

  q.addEventListener('input', apply);
  Object.keys(btn).forEach(function (k) {{
    btn[k].addEventListener('click', function () {{
      on[k] = !on[k];
      btn[k].setAttribute('aria-pressed', on[k] ? 'true' : 'false');
      apply();
    }});
  }});
  apply();
}})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default=os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json"))
    ap.add_argument("--out", default="/tmp/library_index.html")
    a = ap.parse_args()
    rows = build(json.load(open(a.catalogue)))
    if not rows:
        sys.exit("no approved entries — nothing to index")
    open(a.out, "w").write(render(rows, a.catalogue))
    makes = len({r["make"] for r in rows})
    print(f"{a.out}: {len(rows)} approved models, {makes} marques, "
          f"{sum(1 for r in rows if r['ncol']==8)} with all eight colours")


if __name__ == "__main__":
    main()

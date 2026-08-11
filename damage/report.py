"""Assemble the inspection into one report object, and render it to HTML.

The report is the product's face — it is what a claim gets attached to, what a
buyer is sent, what a rental return is signed against. So it does three things
the competitors do piecemeal, together: it leads with the AutoScan-style
headline score, it shows each finding with FairMoto's evidence / hidden-damage
/ model-risk detail, and it carries the repair range and the capture-quality
caveats honestly rather than burying them.

`assemble()` returns a plain dict (the JSON artifact and the app both consume
it). `render_html()` turns that dict into a self-contained, print-ready page —
no external assets, so it is equally a web view and, through the browser's
print-to-PDF, the PDF export FairMoto and magicplan both ship. Keeping the
renderer pure-stdlib (string building, html.escape) means the CI test runner
exercises it with no dependencies.
"""
import html
import time

from severity import summarize
from taxonomy import PANELS, severity_band


def assemble(findings, images=None, meta=None, repair=None, quality=None,
             completeness=None, fusion=None, vehicle=None, scan_id=None,
             generated_at=None):
    """Build the full report dict from the pipeline's parts."""
    roll = summarize(findings)
    report = {
        "type": "vehicle_damage_inspection",
        "version": 1,
        "scan_id": scan_id,
        "generated_at": generated_at or _now(),
        "vehicle": vehicle or {},
        "summary": (meta or {}).get("summary", ""),
        "condition": {
            "score": roll["condition_score"],
            "grade": roll["grade"],
            "descriptor": roll["grade_descriptor"],
            "colour": roll["grade_colour"],
            "structural_concern": roll["structural_concern"],
        },
        "rollup": roll,
        "findings": findings,
        "images": images or [],
        "repair": repair,
        "quality": quality,
        "completeness": completeness,
        "fusion": fusion,
        "disclaimer": (
            "AI-assisted visual inspection from photographs. It supports a "
            "decision; it is not a certified engineer's report. Hidden-damage "
            "items are probabilistic inferences, not observations. Have any "
            "structural or safety finding confirmed in person."),
    }
    return report


def _now():
    # Date.now()-free: the worker stamps time when it builds the report; tests
    # pass a fixed value so output is deterministic.
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- HTML rendering -------------------------------------------------------

def render_html(report):
    """Render the report dict to a self-contained HTML string."""
    v = report.get("vehicle") or {}
    ident = " ".join(str(v[k]) for k in ("year", "make", "model", "trim")
                     if v.get(k)) or "Vehicle"
    cond = report.get("condition", {})
    score = cond.get("score", 100)
    grade = cond.get("grade", "A")
    colour = cond.get("colour", "#3fb950")
    descriptor = cond.get("descriptor", "excellent")

    parts = [_HEAD, f"<h1>{html.escape(ident)}</h1>"]
    parts.append(f'<div class="sub">Damage inspection · '
                 f'{html.escape(str(report.get("generated_at","")))}'
                 + (f' · scan {html.escape(str(report["scan_id"]))}'
                    if report.get("scan_id") else "") + "</div>")

    # headline score gauge
    parts.append(_gauge(score, grade, descriptor, colour))
    if report.get("summary"):
        parts.append(f'<p class="summary">{html.escape(report["summary"])}</p>')
    if cond.get("structural_concern"):
        parts.append('<div class="banner">⚠ Structural or safety damage '
                     'indicated — get this inspected in person before use.</div>')

    # repair headline
    rep = report.get("repair")
    if rep:
        sym = rep.get("symbol", "$")
        line = (f'Estimated repair: <b>{sym}{rep.get("total_low",0):,}'
                f'–{sym}{rep.get("total_high",0):,}</b>')
        if rep.get("hidden_contingency_high"):
            line += (f' <span class="muted">+ up to {sym}'
                     f'{rep["hidden_contingency_high"]:,} if hidden damage '
                     f'confirmed</span>')
        parts.append(f'<div class="repair">{line}<div class="muted small">'
                     f'{html.escape(rep.get("disclaimer",""))}</div></div>')

    # findings
    findings = report.get("findings") or []
    parts.append(f'<h2>Findings <span class="count">{len(findings)}</span></h2>')
    if not findings:
        parts.append('<p class="muted">No damage found in the supplied '
                     'images.</p>')
    for f in findings:
        parts.append(_finding_card(f, rep))

    # capture quality + completeness
    comp = report.get("completeness")
    if comp:
        parts.append(_completeness_block(comp))
    q = report.get("quality")
    if q and q.get("blocking_tags"):
        parts.append('<div class="banner soft">Some images had quality issues ('
                     + html.escape(", ".join(q["blocking_tags"]))
                     + ') — findings on those are less certain.</div>')

    # 3D
    fus = report.get("fusion")
    if fus and fus.get("count"):
        pinned = "attached to the 3D model" if fus.get("fused") \
            else "ready to attach to the 3D model"
        parts.append(f'<h2>3D map</h2><p class="muted">{fus["count"]} finding'
                     f'{"s" if fus["count"]!=1 else ""} {pinned}. '
                     f'Open the vehicle in the app to see the damage pinned in '
                     f'place.</p>')

    parts.append(f'<div class="disclaimer">{html.escape(report.get("disclaimer",""))}</div>')
    parts.append("</div></body></html>")
    return "".join(parts)


def _gauge(score, grade, descriptor, colour):
    pct = max(0, min(100, score))
    return f"""
<div class="gauge">
  <div class="ring" style="background:conic-gradient({colour} {pct*3.6}deg,#20262e 0);">
    <div class="ring-hole"><div class="score" style="color:{colour}">{score}</div>
    <div class="outof">/100</div></div>
  </div>
  <div class="grade">
    <div class="letter" style="color:{colour}">{html.escape(grade)}</div>
    <div class="descriptor">{html.escape(descriptor)}</div>
  </div>
</div>"""


def _finding_card(f, rep):
    sev = f.get("severity", 5)
    band, colour = severity_band(sev)
    panel = PANELS.get(f.get("panel"), (f.get("panel", "Body"),))[0]
    head = (f'<div class="fc-head"><span class="panel">{html.escape(panel)}</span>'
            f'<span class="chip" style="background:{colour}22;color:{colour};'
            f'border-color:{colour}55">{html.escape(f.get("damage_label","Damage"))}'
            f' · sev {sev} · {band}</span></div>')
    body = []
    for e in f.get("evidence", []):
        body.append(f'<li class="ev">▪ {html.escape(e)}</li>')
    ev = f'<ul class="evlist">{"".join(body)}</ul>' if body else ""

    hidden = ""
    if f.get("hidden_damage"):
        rows = []
        for hd in f["hidden_damage"]:
            p = int(round(hd.get("probability", 0) * 100))
            rows.append(f'<li>⚠ <b>{html.escape(hd["system"])}</b> · p={p}% '
                        f'<span class="muted">{html.escape(hd.get("rationale",""))}</span></li>')
        hidden = f'<div class="hidden"><div class="lbl">Possible hidden damage</div>' \
                 f'<ul>{"".join(rows)}</ul></div>'

    risks = ""
    if f.get("model_specific_risks"):
        items = "".join(f"<li>🔧 {html.escape(r)}</li>"
                        for r in f["model_specific_risks"])
        risks = f'<div class="risks"><div class="lbl">Model-specific</div>' \
                f'<ul>{items}</ul></div>'

    cost = ""
    if rep:
        line = next((l for l in rep.get("lines", [])
                     if l.get("panel") == f.get("panel")
                     and l.get("damage_type") == f.get("damage_type")), None)
        if line:
            cost = (f'<div class="cost">{line["symbol"]}{line["low"]:,}–'
                    f'{line["symbol"]}{line["high"]:,} '
                    f'<span class="muted small">({html.escape(line["assumption_low"])} '
                    f'→ {html.escape(line["assumption_high"])})</span></div>')

    note = (f'<div class="note muted small">{html.escape(f["repair_note"])}</div>'
            if f.get("repair_note") else "")
    return (f'<div class="fc" style="border-left-color:{colour}">'
            f'{head}{ev}{hidden}{risks}{cost}{note}</div>')


def _completeness_block(comp):
    pct = int(round(comp.get("overall_coverage", 0) * 100))
    body = [f'<h2>Capture coverage <span class="count">{pct}%</span></h2>']
    if comp.get("guidance"):
        body.append('<ul class="guidance">')
        for g in comp["guidance"]:
            body.append(f'<li>📷 {html.escape(g)}</li>')
        body.append('</ul>')
    else:
        body.append('<p class="muted">Good all-round coverage.</p>')
    return "".join(body)


_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vehicle Damage Inspection</title>
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;background:#0d1117;color:#e6edf3;
    font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
  .wrap{max-width:820px;margin:0 auto;padding:28px 20px 60px}
  h1{font-size:26px;margin:0 0 2px}
  .sub{color:#8b949e;font-size:13px;margin-bottom:18px}
  h2{font-size:18px;margin:28px 0 12px;border-bottom:1px solid #21262d;padding-bottom:6px}
  .count{color:#8b949e;font-weight:400;font-size:14px}
  .muted{color:#8b949e}.small{font-size:12px}
  .gauge{display:flex;align-items:center;gap:22px;margin:8px 0 6px}
  .ring{width:132px;height:132px;border-radius:50%;display:flex;
    align-items:center;justify-content:center;flex:none}
  .ring-hole{width:104px;height:104px;border-radius:50%;background:#0d1117;
    display:flex;flex-direction:column;align-items:center;justify-content:center}
  .score{font-size:40px;font-weight:700;line-height:1}
  .outof{color:#8b949e;font-size:12px}
  .grade .letter{font-size:38px;font-weight:800;line-height:1}
  .grade .descriptor{text-transform:capitalize;color:#8b949e}
  .summary{background:#161b22;border:1px solid #21262d;border-radius:10px;
    padding:12px 14px}
  .banner{background:#3d1d1d;border:1px solid #6e2b2b;color:#ffb3b3;
    border-radius:8px;padding:10px 14px;margin:12px 0;font-weight:600}
  .banner.soft{background:#2b2410;border-color:#5c4c17;color:#e3c98a;font-weight:400}
  .repair{background:#161b22;border:1px solid #21262d;border-radius:10px;
    padding:12px 14px;margin:14px 0}
  .repair b{font-size:18px}
  .fc{background:#161b22;border:1px solid #21262d;border-left-width:4px;
    border-radius:10px;padding:12px 14px;margin:10px 0}
  .fc-head{display:flex;justify-content:space-between;align-items:center;gap:10px;
    flex-wrap:wrap}
  .panel{font-weight:700}
  .chip{border:1px solid;border-radius:999px;padding:2px 10px;font-size:12px;
    font-weight:600;white-space:nowrap}
  .evlist{margin:8px 0 4px;padding:0;list-style:none}
  .ev{color:#c9d1d9;font-size:14px}
  .hidden,.risks{margin-top:8px;background:#0f141a;border:1px dashed #30363d;
    border-radius:8px;padding:8px 10px}
  .hidden .lbl,.risks .lbl{font-size:11px;text-transform:uppercase;
    letter-spacing:.05em;color:#8b949e;margin-bottom:4px}
  .hidden ul,.risks ul{margin:0;padding-left:2px;list-style:none}
  .hidden li,.risks li{font-size:13px;margin:3px 0}
  .cost{margin-top:8px;font-weight:600}
  .guidance{list-style:none;padding:0}.guidance li{margin:4px 0}
  .disclaimer{margin-top:34px;color:#6e7681;font-size:12px;border-top:1px solid #21262d;
    padding-top:14px}
  @media print{body{background:#fff;color:#111}
    .fc,.summary,.repair{background:#fafafa;border-color:#ddd}
    .ring-hole{background:#fff}}
</style></head><body><div class="wrap">"""

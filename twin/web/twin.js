/* Stages 2-5 in one workspace: map, 3D, floor plan, editor.
 *
 * The three views are windows on ONE project. Every edit — a wall
 * dragged in the plan, a button, a typed sentence — goes to
 * /api/project/<id>/command and the whole state comes back; all three
 * views then redraw from it. That is why 2D and 3D cannot drift apart:
 * neither of them owns anything.
 */
import { Viewer3D } from './render3d.js';
import { PlanView } from './plan.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let project = null;      // last full state payload
let viewer = null;
let plan = null;
let baseline = null;     // as-found massing, for before/after
let showBaseline = false;

function status(msg, ms = 4000) {
  const el = $('tstatus');
  if (!msg) { el.style.display = 'none'; return; }
  el.textContent = msg;
  el.style.display = 'block';
  clearTimeout(status._t);
  if (ms) status._t = setTimeout(() => (el.style.display = 'none'), ms);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, body };
}

async function post(path, payload) {
  return api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
}

/* --- opening a twin --------------------------------------------------- */
export async function openTwin(lat, lon) {
  status('Building the twin…', 0);
  const { body } = await post('/api/project', { lat, lon });
  if (!body.available) {
    status(`Cannot build a twin here — ${body.reason || 'no building'}`, 8000);
    return null;
  }
  project = body;
  $('workspace').style.display = 'flex';
  ensureViews();
  const b = await api(`/api/project/${body.project_id}/baseline`);
  baseline = b.body && b.body.available ? b.body.massing : null;
  render();
  status('');
  refreshAssessment();
  return body;
}

function ensureViews() {
  if (!viewer) {
    try {
      viewer = new Viewer3D($('view3d'));
    } catch (e) {
      $('view3d').replaceWith(Object.assign(document.createElement('div'), {
        className: 'na', textContent: '3D unavailable: ' + e.message }));
    }
  }
  if (!plan) {
    plan = new PlanView($('viewplan'));
    plan.onPick = (wall) => {
      $('selInfo').textContent =
        `${wall.edge} wall · ${wall.length_m} m · ` +
        `${wall.external ? 'external' : 'internal'}`;
    };
    /* THE DIRECT-MANIPULATION PATH. A dragged wall becomes the same
     * validated command a typed instruction would produce. */
    plan.onDrag = (wall, by) => {
      applyCommand({ kind: 'move_wall', block_id: wall.block,
                     edge: wall.edge, by_m: by,
                     label: `${wall.edge} wall ${by > 0 ? '+' : ''}${by} m` });
    };
  }
}

/* --- the one write path ----------------------------------------------- */
async function applyCommand(payload) {
  if (!project) return;
  status('Applying…', 0);
  const { body, status: code } = await post(
    `/api/project/${project.project_id}/command`, payload);
  if (code === 422 || !body.available) {
    status(`REFUSED — ${body.reason || 'that edit is not possible'}`, 9000);
    render();                       // put the ghost away
    return;
  }
  project = body;
  status('');
  render();
  refreshAssessment();
}

async function historyAction(what) {
  if (!project) return;
  const { body, status: code } = await post(
    `/api/project/${project.project_id}/${what}`);
  if (code === 422) { status(body.reason, 3000); return; }
  project = body;
  render();
  refreshAssessment();
}

/* --- rendering all three views from one state ------------------------- */
function render() {
  if (!project) return;
  const massing = showBaseline && baseline ? baseline : project.massing;
  if (viewer) viewer.setMassing(massing, { frame: !render._framed });
  render._framed = true;
  if (plan) plan.set(project.plan, project.building.anchor.bearing_deg);
  drawLevels();
  drawHistory();
  drawSummary();
}

function drawSummary() {
  const m = project.building.measurements;
  const rows = [
    ['Footprint', `${m.footprint_m2} m²`],
    ['Floor area (GIA)', `${m.gia_m2} m²`],
    ['Eaves', `${m.eaves_height_m} m`],
    ['Ridge', `${m.ridge_height_m} m`],
  ];
  $('summary').innerHTML = rows.map(([k, v]) =>
    `<div class="kv"><span>${k}</span><span>${v}</span></div>`).join('') +
    (project.building.notes || []).map((n) =>
      `<div class="warn">${esc(n)}</div>`).join('');
}

function drawLevels() {
  const n = (project.plan.levels || []).length;
  const box = $('levels');
  box.innerHTML = '';
  for (let i = n - 1; i >= 0; i--) {
    const b = document.createElement('button');
    b.textContent = i === 0 ? 'Ground' : `Floor ${i}`;
    b.className = plan && plan.level === i ? 'on' : '';
    b.onclick = () => { plan.level = i; plan.fit(); drawLevels(); };
    box.appendChild(b);
  }
}

function drawHistory() {
  const h = project.history;
  $('undo').disabled = !h.can_undo;
  $('redo').disabled = !h.can_redo;
  $('hist').innerHTML = h.applied.length
    ? h.applied.map((c, i) =>
        `<div class="hrow" data-v="${i + 1}">${i + 1}. ${esc(c.label)}</div>`
      ).join('')
    : '<div class="hrow dim">as found — no edits yet</div>';
  for (const el of $('hist').querySelectorAll('.hrow[data-v]')) {
    el.onclick = async () => {
      const { body } = await post(
        `/api/project/${project.project_id}/restore`,
        { version: Number(el.dataset.v) });
      if (body.available) { project = body; render(); refreshAssessment(); }
    };
  }
}

/* --- the real engine's answer ----------------------------------------- */
async function refreshAssessment() {
  if (!project) return;
  $('assess').innerHTML = '<div class="dim">checking…</div>';
  const region = $('region') ? $('region').value : '';
  const vat = $('vat') ? $('vat').value : 'standard';
  const cal = $('calRate') && $('calRate').value
    ? `&calibrate_per_m2=${encodeURIComponent($('calRate').value)}` : '';
  const { body } = await api(
    `/api/project/${project.project_id}/assess?region=${region}&vat=${vat}${cal}`);
  if (!body.available) {
    $('assess').innerHTML = `<div class="na">DATA NOT AVAILABLE<small>${
      esc(body.reason)}</small></div>`;
    return;
  }
  const c = body.compliance || {};
  let html = '';
  if (c.available === false) {
    html += `<div class="na">${esc(c.reason)}</div>`;
  } else {
    const massing = c.stage === 'massing';
    html += `<div class="verdict ${massing ? 'v-massing'
      : c.buildable ? 'v-ok' : 'v-no'}">` +
      (massing ? 'MASSING — rooms not drawn yet'
        : c.buildable ? 'PASSES the regulations gate'
        : `REFUSED — ${c.counts.refuse} issue(s)`) + '</div>';
    if (c.note) html += `<div class="dim small">${esc(c.note)}</div>`;
    if (!massing && (c.findings || []).length) {
      html += (c.findings || []).slice(0, 6).map((f) =>
        `<div class="finding f-${f.severity}"><b>${esc(f.code)}</b> ${
          esc(f.message).slice(0, 160)}</div>`).join('');
    }
  }
  const t = body.totals || {};
  html += `<div class="kv"><span>Engine GIA</span><span>${
    t.floor_area_m2 ?? '—'} m²</span></div>`;
  html += `<div class="kv"><span>Ridge</span><span>${
    t.ridge_height_m ?? '—'} m</span></div>`;

  const q = body.quantities;
  if (q && q.groups) {
    html += '<details open><summary>Bill of quantities</summary>';
    for (const [trade, lines] of Object.entries(q.groups)) {
      if (!lines.length) continue;
      html += `<div class="trade">${esc(trade)}</div>`;
      html += lines.slice(0, 8).map((L) =>
        `<div class="kv"><span>${esc(L.item)}</span><span>${L.quantity} ${
          esc(L.unit)}</span></div>`).join('');
    }
    html += '</details>';
  } else if (q) {
    html += `<div class="na small">${esc(q.reason || '')}</div>`;
  }
  const e = body.estimate;
  if (e && e.available !== false) {
    const t = e.totals, pm = e.per_m2;
    html += `<div class="sect"><h3>Estimate</h3>`;
    html += `<div class="price">£${Math.round(t.gross).toLocaleString()}` +
      `<span class="dim small"> incl VAT</span></div>`;
    html += `<div class="dim small">realistic range £${
      Math.round(t.range_low).toLocaleString()} – £${
      Math.round(t.range_high).toLocaleString()}</div>`;
    if (pm) {
      const band = /inside/.test(pm.verdict) ? 'v-ok' : 'v-massing';
      html += `<div class="verdict ${band}" style="margin-top:7px">£${
        pm.gross_per_m2.toLocaleString()} / m²</div>`;
      html += `<div class="dim small">${esc(pm.verdict)}</div>`;
    }
    html += [['Materials', e.materials.total],
             [`Labour (${e.labour.hours} hrs)`, e.labour.total],
             ['Preliminaries', e.preliminaries.total],
             ['Overhead &amp; profit', e.overhead_profit.total],
             ['Contingency', e.contingency.total],
             ['Professional fees', e.professional_fees.total],
             [`VAT ${(t.vat_rate * 100).toFixed(0)}%`, t.vat]]
      .map(([k, v]) => `<div class="kv"><span>${k}</span><span>£${
        Math.round(v).toLocaleString()}</span></div>`).join('');
    if (e.status === 'PARTIAL') {
      html += `<div class="warn">PARTIAL PRICE — excludes ${
        esc(e.excludes.join('; '))}</div>`;
    }
    html += `<div class="warn">${esc(e.rate_provenance.confidence)}</div>`;
    html += `<details><summary>Rates &amp; VAT</summary><div class="prov">` +
      `${esc(e.rate_provenance.basis)}<br><br>${esc(e.vat_basis)}` +
      `<br><br>${esc(e.disclaimer)}</div></details>`;
    html += `</div>`;
  } else if (e) {
    html += `<div class="na small">${esc(e.reason || '')}</div>`;
  }
  $('assess').innerHTML = html;
}

/* --- wiring ------------------------------------------------------------ */
export function initTwinUI() {
  $('undo').onclick = () => historyAction('undo');
  $('redo').onclick = () => historyAction('redo');

  $('extendBtn').onclick = () => {
    const depth = parseFloat($('extDepth').value);
    if (!(depth > 0)) { status('Enter a depth in metres', 3000); return; }
    applyCommand({ kind: 'extend', block_id: 'existing',
                   edge: $('extEdge').value,
                   depth_m: depth,
                   storeys: parseInt($('extStoreys').value, 10),
                   label: `${depth} m ${$('extEdge').value} extension` });
  };

  $('askBtn').onclick = () => {
    const t = $('ask').value.trim();
    if (!t) return;
    applyCommand({ text: t });
    $('ask').value = '';
  };
  $('ask').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('askBtn').click();
  });

  for (const btn of document.querySelectorAll('#views button[data-view]')) {
    btn.onclick = () => {
      if (viewer) viewer.setView(btn.dataset.view);
      for (const b of document.querySelectorAll('#views button[data-view]')) {
        b.className = b === btn ? 'on' : '';
      }
    };
  }
  $('projBtn').onclick = () => {
    if (!viewer) return;
    const ortho = viewer.projection !== 'ortho';
    viewer.setProjection(ortho ? 'ortho' : 'perspective');
    $('projBtn').textContent = ortho ? 'Orthographic' : 'Perspective';
  };

  for (const id of ['region', 'vat', 'calRate']) {
    const el = $(id);
    if (el) el.onchange = () => refreshAssessment();
  }
  $('beforeAfter').onchange = (e) => {
    showBaseline = e.target.checked;
    render._framed = true;
    render();
  };

  $('sunTime').oninput = () => {
    if (!viewer || !project) return;
    const a = project.building.anchor;
    const d = new Date(Date.UTC(2026, 5, 21,
                                Math.floor($('sunTime').value), 0));
    const s = viewer.setSun(a.lat, a.lon, d);
    $('sunLabel').textContent =
      `21 Jun ${String(Math.floor($('sunTime').value)).padStart(2, '0')}:00 · ` +
      `sun ${s.altitude_deg.toFixed(0)}° alt ${s.azimuth_deg.toFixed(0)}° az` +
      (s.above_horizon ? '' : ' (below horizon)');
  };

  $('closeTwin').onclick = () => {
    $('workspace').style.display = 'none';
  };

  for (const t of document.querySelectorAll('#tabs button')) {
    t.onclick = () => {
      for (const o of document.querySelectorAll('#tabs button')) {
        o.className = o === t ? 'on' : '';
      }
      $('pane3d').style.display = t.dataset.tab === '3d' ? 'block' : 'none';
      $('paneplan').style.display = t.dataset.tab === 'plan' ? 'block' : 'none';
      if (t.dataset.tab === '3d' && viewer) viewer.resize();
      if (t.dataset.tab === 'plan' && plan) { plan.resize(); plan.fit(); }
    };
  }
}

window.__twinUI = { openTwin, applyCommand, get project() { return project; },
                    get viewer() { return viewer; },
                    get plan() { return plan; }, render, refreshAssessment };

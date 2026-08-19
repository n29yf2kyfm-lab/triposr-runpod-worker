/* The Stage 1 application: search the world, load real footprints,
 * select a property, read what is actually known about it.
 *
 * THE ONE RULE THIS FILE ENFORCES ON SCREEN: nothing is rendered as a
 * fact unless the API returned it with provenance. Every value carries
 * its classification badge, every absent layer renders DATA NOT
 * AVAILABLE with the reason the provider gave, and the provenance chain
 * is one disclosure click away on every single number.
 */
import { MapEngine, GeoJSONLayer, scaleBar, bboxOf } from './engine.js';

const $ = (id) => document.getElementById(id);
const map = new MapEngine($('map'), { centre: [-1.8476, 52.4856], zoom: 3 });

const buildings = map.addLayer(new GeoJSONLayer('buildings', { zIndex: 10 }));
/* The selected building keeps ITS OWN classification. Styling the
 * selection layer as 'user' painted a verified OSM footprint in the
 * green reserved for geometry the user drew — mislabelling provenance
 * on screen, which is the one thing this product must never do. The
 * selection is shown by weight and fill, not by changing what the
 * colour means. */
const selection = map.addLayer(new GeoJSONLayer('selection', { zIndex: 20 }));

let lastBoundsKey = null;
let inflight = null;

function status(msg, ms = 4200) {
  const el = $('status');
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

/* --- search --------------------------------------------------------- */
async function search() {
  const q = $('q').value.trim();
  if (!q) return;
  $('go').disabled = true;
  status('Searching…', 0);
  const { body } = await api('/api/search?q=' + encodeURIComponent(q));
  $('go').disabled = false;
  const box = $('results');
  box.innerHTML = '';
  if (!body.available) {
    status(`DATA NOT AVAILABLE — ${body.reason || 'no match'}` +
           (body.detail ? ` (${body.detail})` : ''), 8000);
    return;
  }
  status('');
  for (const hit of body.value) {
    const div = document.createElement('div');
    div.className = 'res';
    div.innerHTML =
      `<b>${escapeHtml(hit.label || '')}</b>` +
      `<div class="sub">${escapeHtml(hit.type || '')} · ` +
      `±${Math.round(hit.accuracy_m)} m · ${hit.lat.toFixed(5)}, ` +
      `${hit.lon.toFixed(5)}</div>` +
      (hit.note ? `<div class="sub">${escapeHtml(hit.note)}</div>` : '');
    div.onclick = () => {
      box.innerHTML = '';
      // A postcode centroid is not a house: zoom to a level where the
      // user can see which building is theirs and pick it.
      const z = hit.accuracy_m <= 10 ? 19 : hit.accuracy_m <= 150 ? 18 : 15;
      map.setView([hit.lon, hit.lat], z);
      loadBuildings(true);
    };
    box.appendChild(div);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* --- footprints ------------------------------------------------------ */
async function loadBuildings(force, attempt = 0) {
  if (map.zoom < 16) {
    buildings.data = null;
    map.render();
    status('Zoom in to load building footprints', 2500);
    return;
  }
  const [w, s, e, n] = map.bounds();
  const key = [w, s, e, n].map((v) => v.toFixed(4)).join(',');
  if (!force && key === lastBoundsKey) return;
  lastBoundsKey = key;
  if (inflight) inflight.abort();
  inflight = new AbortController();
  try {
    const { body } = await api(
      `/api/buildings?west=${w}&south=${s}&east=${e}&north=${n}`,
      { signal: inflight.signal });
    if (!body.available) {
      // A COLD OVERPASS CALL CAN LOSE ITS FIRST MIRROR. That is a
      // transport failure, not "there are no buildings here", and the
      // two must not look the same to the user: retry the transport
      // once, and only then report it.
      const transport = /failed to reach/.test(body.reason || '');
      if (transport && attempt < 1) {
        status('Footprint server slow — retrying…', 0);
        lastBoundsKey = null;
        return loadBuildings(true, attempt + 1);
      }
      buildings.data = null;
      map.render();
      status(`DATA NOT AVAILABLE — ${body.reason}` +
             (body.detail ? ` ${body.detail}` : ''), 8000);
      return;
    }
    status('');
    buildings.data = body.value;
    map.render();
    attribution(body.provenance);
  } catch (err) {
    if (err.name !== 'AbortError') status('Footprint request failed: ' + err);
  }
}

function attribution(prov) {
  const lines = new Set(($('attrib').textContent || '')
    .split('\n').filter(Boolean));
  if (prov && prov.source_dataset === 'openstreetmap') {
    lines.add('© OpenStreetMap contributors (ODbL)');
  }
  $('attrib').textContent = [...lines].join('\n');
}

/* --- property panel -------------------------------------------------- */
function badge(cls) {
  return `<span class="badge b-${cls}">${cls}</span>`;
}

function provBlock(p) {
  if (!p) return '';
  const bits = [
    ['source', `${p.source_provider} / ${p.source_dataset}`],
    ['id', p.source_identifier],
    ['licence', p.licence],
    ['observed', p.observation_date || 'not published by the source'],
    ['retrieved', p.retrieval_date],
    ['accuracy', p.accuracy_m != null ? `±${p.accuracy_m} m` : null],
    ['confidence', p.confidence != null ? p.confidence.toFixed(2) : null],
    ['method', p.processing_method],
    ['chain', (p.chain || []).join(' ← ')],
  ].filter(([, v]) => v);
  return `<details><summary>Provenance</summary><div class="prov">` +
    bits.map(([k, v]) => `<div><code>${k}</code>: ${escapeHtml(v)}</div>`)
      .join('') + `</div></details>`;
}

function na(block) {
  return `<div class="na">DATA NOT AVAILABLE` +
    `<small>${escapeHtml(block.reason || '')}` +
    (block.detail ? `<br>${escapeHtml(block.detail)}` : '') +
    (block.asked && block.asked.length
      ? `<br>asked: ${block.asked.join(', ')}` : '') +
    `</small></div>`;
}

function kv(k, v) {
  return `<div class="kv"><span>${k}</span><span>${v}</span></div>`;
}

async function selectProperty(lon, lat) {
  status('Reading the property…', 0);
  const { body } = await api(`/api/property?lat=${lat}&lon=${lon}`);
  status('');
  /* Elevation reads a LIDAR raster and can take tens of seconds. It is
   * fetched on its own so the panel appears immediately and gains the
   * height when it arrives, rather than the whole thing hanging. */
  fetchElevation(lat, lon);
  const el = $('prop');
  el.style.display = 'block';

  const b = body.building;
  selection.data = b.available
    ? { type: 'FeatureCollection', features: [b.value] } : null;
  if (b.available) {
    selection.selectedId = b.value.id;      // draws it as selected
    buildings.selectedId = b.value.id;
    map.fitBounds(bboxOf(b.value.geometry), 0.55);
  }
  map.render();

  const a = body.address;
  const m = body.measurements;
  const st = body.storeys;
  const el2 = body.elevation;

  let html = `<h2>${a.available
    ? escapeHtml(a.value.house_number
        ? `${a.value.house_number} ${a.value.road || ''}`
        : a.value.road || a.value.label.split(',')[0])
    : 'Unidentified location'}</h2>`;
  html += `<div class="addr">${a.available
    ? escapeHtml(a.value.label) : 'no address record'}</div>`;

  html += `<div class="sect"><h3>Location</h3>`;
  html += kv('Latitude', body.query.lat.toFixed(6));
  html += kv('Longitude', body.query.lon.toFixed(6));
  if (a.available) {
    html += kv('Postcode', escapeHtml(a.value.postcode || '—'));
    html += kv('Country', escapeHtml(a.value.country || '—'));
    html += provBlock(a.provenance);
  } else { html += na(a); }
  html += `</div>`;

  html += `<div class="sect"><h3>Building footprint ${
    b.available ? badge(b.classification) : ''}</h3>`;
  if (b.available && m.available) {
    html += kv('Footprint area', `${m.value.footprint_area_m2} m²`);
    html += kv('Perimeter', `${m.value.perimeter_m} m`);
    html += kv('Corners', m.value.vertices);
    html += kv('OSM id', escapeHtml(b.value.properties.osm_id));
    html += provBlock(m.provenance);
  } else { html += na(b.available ? m : b); }
  html += `</div>`;

  html += `<div class="sect"><h3>Storeys &amp; height</h3>`;
  if (st.available) {
    if (st.value.levels != null) html += kv('Storeys (OSM tag)', st.value.levels);
    if (st.value.height_m != null) html += kv('Height (OSM tag)', `${st.value.height_m} m`);
    html += provBlock(st.provenance);
  } else { html += na(st); }
  html += `</div>`;

  html += `<div class="sect"><h3>Elevation ${badge('derived')}</h3>` +
    `<div id="elevSlot"><div class="kv"><span>Ground</span>` +
    `<span>measuring…</span></div></div></div>`;

  if (body.height_cross_check) {
    const c = body.height_cross_check;
    html += `<div class="sect"><h3>Cross-check</h3>`;
    html += kv('LIDAR', `${c.lidar_m} m`);
    html += kv('OSM tag', `${c.osm_tag_m} m`);
    html += kv('Difference', `${c.difference_m} m`);
    html += kv('Agree', c.agree ? 'yes' : 'NO — treat both as unconfirmed');
    html += `</div>`;
  }

  html += `<div class="sect"><h3>Parcel</h3>`;
  html += body.parcel.available ? kv('Available', 'yes') : na(body.parcel);
  html += `</div>`;

  const caps = body.capabilities.layers;
  html += `<div class="sect"><h3>Data available in ${
    escapeHtml(body.capabilities.country || 'this country')}</h3>`;
  for (const [layer, c] of Object.entries(caps)) {
    const colour = c.level === 'AVAILABLE' ? 'var(--user)'
      : c.level === 'LIMITED' ? 'var(--accent)' : 'var(--bad)';
    html += `<div class="kv"><span>${layer}</span>` +
      `<span style="color:${colour}">${c.level}</span></div>`;
  }
  html += `<details><summary>Why</summary><div class="prov">` +
    Object.entries(caps).map(([l, c]) =>
      `<div><code>${l}</code>: ${escapeHtml(c.note || '')}</div>`).join('') +
    `</div></details></div>`;

  el.innerHTML = html;
}

async function fetchElevation(lat, lon) {
  const slot = () => document.getElementById('elevSlot');
  if (slot()) slot().innerHTML =
    '<div class="kv"><span>Ground</span><span>measuring…</span></div>';
  const { body } = await api(`/api/elevation?lat=${lat}&lon=${lon}`);
  const el = slot();
  if (!el) return;
  el.innerHTML = body.available
    ? kv('Ground', `${body.value.ground_m_aod} m AOD`) +
      kv('Surface', `${body.value.surface_m_aod} m AOD`) +
      kv('Height above ground', `${body.value.height_above_ground_m} m`) +
      provBlock(body.provenance)
    : na(body);
}

/* --- wiring ---------------------------------------------------------- */
$('go').onclick = search;
$('q').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

map.on('click', ({ lon, lat, hit }) => {
  if (hit) buildings.selectedId = hit.feature.id;
  selectProperty(lon, lat);
});

let moveTimer = null;
map.on('move', () => {
  clearTimeout(moveTimer);
  moveTimer = setTimeout(() => loadBuildings(false), 320);
  const sb = scaleBar(map.metresPerPixel());
  $('scaleTxt').textContent =
    `${sb.label} · ${map.metresPerPixel().toFixed(3)} m/px · z${map.zoom.toFixed(1)}`;
  $('bar').style.width = sb.px + 'px';
});

map.emit('move', map.viewState());

/* Expose for the test harness — assertions run against the real engine
 * state, not against a screenshot. */
window.__twin = { map, buildings, selection, loadBuildings, selectProperty,
                  scaleBar };

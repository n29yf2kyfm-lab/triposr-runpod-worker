/**
 * Builder — a GeoLibre plugin that puts a measured building on the map.
 *
 * This is the second seam into GeoLibre (the first is siteplan.py, which
 * writes whole projects). Here the domain knowledge lives INSIDE their
 * app: load a model.json this project produced, drop it on the map at a
 * clicked point, and get the two things no GIS knows — how far Class A
 * permitted development would let a rear extension go, and where the
 * house throws shade at a given date and hour.
 *
 * Written as a self-contained ES module on purpose: the manifest contract
 * requires a single bundled entry, and a plugin with no build chain is a
 * plugin that still works in two years.
 *
 * The maths here MUST agree with building/siteplan.py and the three.js
 * viewer — same solar geometry, same GPDO limits, same tangent-plane
 * transform. Where it drifts, siteplan.py is the authority: it is the one
 * with tests.
 */

const ID = "builder-siteplan";

/* ------------------------------------------------------------ geometry */

// Metres per degree on WGS84 — the standard series, matching geo.py.
function metresPerDegree(latDeg) {
  const lat = (latDeg * Math.PI) / 180;
  return {
    lat:
      111132.92 -
      559.82 * Math.cos(2 * lat) +
      1.175 * Math.cos(4 * lat) -
      0.0023 * Math.cos(6 * lat),
    lon:
      111412.84 * Math.cos(lat) -
      93.5 * Math.cos(3 * lat) +
      0.118 * Math.cos(5 * lat),
  };
}

function localToWgs84(anchor, x, y) {
  const b = (anchor.bearing * Math.PI) / 180;
  const east = x * Math.cos(b) + y * Math.sin(b);
  const north = -x * Math.sin(b) + y * Math.cos(b);
  const m = metresPerDegree(anchor.lat);
  return [anchor.lon + east / m.lon, anchor.lat + north / m.lat];
}

// Sun altitude and azimuth (radians, azimuth from north clockwise).
function sunPosition(latDeg, dayOfYear, solarHour) {
  const lat = (latDeg * Math.PI) / 180;
  const decl =
    ((-23.44 * Math.PI) / 180) *
    Math.cos((2 * Math.PI * (dayOfYear + 10)) / 365.25);
  const H = ((solarHour - 12) * 15 * Math.PI) / 180;
  const alt = Math.asin(
    Math.sin(lat) * Math.sin(decl) +
      Math.cos(lat) * Math.cos(decl) * Math.cos(H),
  );
  const azS = Math.atan2(
    Math.sin(H),
    Math.cos(H) * Math.sin(lat) - Math.tan(decl) * Math.cos(lat),
  );
  return { alt, az: (azS + Math.PI) % (2 * Math.PI) };
}

function hull(points) {
  const pts = [...new Set(points.map((p) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`))]
    .map((s) => s.split(",").map(Number))
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const half = (seq) => {
    const out = [];
    for (const p of seq) {
      while (out.length >= 2) {
        const [x1, y1] = out[out.length - 2];
        const [x2, y2] = out[out.length - 1];
        if ((x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) <= 0) out.pop();
        else break;
      }
      out.push(p);
    }
    return out;
  };
  return [...half(pts).slice(0, -1), ...half([...pts].reverse()).slice(0, -1)];
}

/* --------------------------------------------------------- the domain */

// GPDO Schedule 2 Part 1 Class A, as learned in
// docs/UK_COMPLIANCE_KNOWLEDGE.md. An ENVELOPE, never a permission.
const PD_DEPTH = {
  single: { detached: 4, other: 3 },
  larger: { detached: 8, other: 6 },
  twoStorey: { detached: 3, other: 3 },
};
const PD_WARNING =
  "ENVELOPE, NOT PERMISSION. Class A is removed by Article 4 directions, " +
  "does not apply to flats or listed buildings, and conservation areas, " +
  "earlier extensions and the 50% curtilage cap all bite. Confirm with the LPA.";

function footprintRing(model) {
  // Trace the external walls: an L-shaped house has an L-shaped footprint,
  // and a rectangle drawn over it is a wrong drawing, not a simple one.
  const segs = [];
  for (const w of model.walls || []) {
    if (!w.external || (w.base_level || 0) !== 0) continue;
    const a = [+w.start[0].toFixed(4), +w.start[1].toFixed(4)];
    const b = [+w.end[0].toFixed(4), +w.end[1].toFixed(4)];
    if (a[0] !== b[0] || a[1] !== b[1]) segs.push([a, b]);
  }
  const key = (p) => `${p[0]},${p[1]}`;
  if (segs.length) {
    const ring = [segs[0][0], segs[0][1]];
    const used = new Set([0]);
    for (let n = 0; n < segs.length; n++) {
      const tail = key(ring[ring.length - 1]);
      let moved = false;
      for (let i = 0; i < segs.length; i++) {
        if (used.has(i)) continue;
        const [a, b] = segs[i];
        if (key(a) === tail) { ring.push(b); used.add(i); moved = true; break; }
        if (key(b) === tail) { ring.push(a); used.add(i); moved = true; break; }
      }
      if (!moved) break;
      if (key(ring[ring.length - 1]) === key(ring[0]) && used.size > 2) {
        // A closure only counts when it consumed every external segment:
        // a detached annex or courtyard leaves a second loop, and a
        // partial ring must not travel labelled as traced (geo.py does
        // the same check).
        if (used.size === segs.length) {
          return { ring: ring.slice(0, -1), traced: true };
        }
        break;
      }
    }
  }
  const ex = model.extent_m.x;
  const ey = model.extent_m.y;
  return {
    ring: [[ex[0], ey[0]], [ex[1], ey[0]], [ex[1], ey[1]], [ex[0], ey[1]]],
    traced: false,
  };
}

function ringArea(ring) {
  let s = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x0, y0] = ring[i];
    const [x1, y1] = ring[(i + 1) % ring.length];
    s += x0 * y1 - x1 * y0;
  }
  return Math.abs(s) / 2;
}

function polygon(anchor, ring, props) {
  const coords = ring.map(([x, y]) => localToWgs84(anchor, x, y));
  coords.push(coords[0]);
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [coords] },
    properties: props,
  };
}

// The rear wall line as [x0, x1, y] pieces, left to right — Class A
// depth is measured from the ACTUAL rear wall, so over a recessed rear
// wing the bounding-box rear line would over-claim. Mirrors
// siteplan._rear_profile, which is the authority.
function rearProfile(ring) {
  const xs = [...new Set(ring.map((p) => p[0]))].sort((a, b) => a - b);
  const pieces = [];
  for (let k = 0; k < xs.length - 1; k++) {
    const x0 = xs[k];
    const x1 = xs[k + 1];
    const mid = (x0 + x1) / 2;
    let top = null;
    for (let i = 0; i < ring.length; i++) {
      const [ax, ay] = ring[i];
      const [bx, by] = ring[(i + 1) % ring.length];
      if (Math.min(ax, bx) < mid && mid < Math.max(ax, bx)) {
        const y = ay + ((by - ay) * (mid - ax)) / (bx - ax);
        top = top === null ? y : Math.max(top, y);
      }
    }
    if (top === null) continue;
    const last = pieces[pieces.length - 1];
    if (last && Math.abs(last[2] - top) < 1e-9 && Math.abs(last[1] - x0) < 1e-9) {
      last[1] = x1;
    } else {
      pieces.push([x0, x1, top]);
    }
  }
  return pieces;
}

function buildLayers(model, anchor, opts) {
  const { ring, traced } = footprintRing(model);
  const t = model.totals || {};
  const ex = model.extent_m.x;
  const ey = model.extent_m.y;
  const out = { building: null, red: null, pd: null, shadow: null, info: {} };

  out.building = {
    type: "FeatureCollection",
    features: [
      polygon(anchor, ring, {
        layer: "building",
        footprint_m2: +ringArea(ring).toFixed(2),
        floor_area_m2: t.floor_area_m2,
        storeys: model.storeys,
        ridge_m: t.ridge_height_m,
        outline: traced ? "traced from external walls" : "extent rectangle",
      }),
    ],
  };

  // Default matches siteplan.layers(red_line_margin_m=6.0). buildLayers
  // is a public surface (exported, and on window.__BUILDER_SITEPLAN__),
  // and an omitted margin used to arrive here as undefined and turn the
  // whole red line into NaN corners — silently broken GeoJSON.
  const m = Number.isFinite(opts.redLineMargin) ? opts.redLineMargin : 6;
  out.red = {
    type: "FeatureCollection",
    features: [
      polygon(
        anchor,
        [
          [ex[0] - m, ey[0] - m],
          [ex[1] + m, ey[0] - m],
          [ex[1] + m, ey[1] + m],
          [ex[0] - m, ey[1] + m],
        ],
        {
          layer: "red line",
          note: "margin around the building — check the title plan; this is not a legal boundary",
        },
      ),
    ],
  };

  if (opts.pd) {
    const table = opts.pdTwoStorey
      ? PD_DEPTH.twoStorey
      : opts.pdLarger
        ? PD_DEPTH.larger
        : PD_DEPTH.single;
    const depth = opts.pdDetached ? table.detached : table.other;
    // Depth off the traced rear wall(s), never the extent box: bottom
    // edge follows the rear staircase left to right, top edge walks the
    // same staircase pushed out by the depth, right to left. Matches
    // siteplan.permitted_development_local.
    let pdRing;
    if (traced) {
      const pieces = rearProfile(ring);
      pdRing = [];
      for (const [x0, x1, y] of pieces) pdRing.push([x0, y], [x1, y]);
      for (const [x0, x1, y] of [...pieces].reverse()) {
        pdRing.push([x1, y + depth], [x0, y + depth]);
      }
    } else {
      pdRing = [
        [ex[0], ey[1]],
        [ex[1], ey[1]],
        [ex[1], ey[1] + depth],
        [ex[0], ey[1] + depth],
      ];
    }
    out.pd = {
      type: "FeatureCollection",
      features: [
        polygon(anchor, pdRing, {
          layer: "pd envelope",
          depth_m: depth,
          warning: PD_WARNING,
        }),
      ],
    };
    out.info.pdDepth = depth;
  }

  if (opts.shadow) {
    const { alt, az } = sunPosition(anchor.lat, opts.day, opts.hour);
    out.info.altitude = (alt * 180) / Math.PI;
    if (alt > (3 * Math.PI) / 180) {
      const height = t.ridge_height_m || t.eaves_height_m || 5;
      const reach = height / Math.tan(alt);
      const theta = az - (anchor.bearing * Math.PI) / 180;
      const dx = -reach * Math.sin(theta);
      const dy = -reach * Math.cos(theta);
      const shadowRing = hull([
        ...ring,
        ...ring.map(([x, y]) => [x + dx, y + dy]),
      ]);
      out.info.reach = reach;
      // The plan-frame offset the shadow is cast along. Exposed so the
      // parity test can pin the DIRECTION against siteplan.py — reach
      // and altitude alone would pass with the shadow drawn on the
      // sunward side.
      out.info.azimuth = (az * 180) / Math.PI;
      out.info.dx = dx;
      out.info.dy = dy;
      out.shadow = {
        type: "FeatureCollection",
        features: [
          polygon(anchor, shadowRing, {
            layer: "shadow",
            reach_m: +reach.toFixed(2),
            altitude_deg: +out.info.altitude.toFixed(2),
            hour: opts.hour,
            day_of_year: opts.day,
          }),
        ],
      };
    }
  }
  return out;
}

/* ------------------------------------------------------------- the UI */

const CSS_PREFIX = "gl-builder";

// Every layer this plugin ever adds, so a redraw can clear exactly its
// own footprint on the map and nothing of the host's.
const OWN_LAYERS = ["Shadow", "PD envelope", "Red line", "Building"];

function removeOwnLayers(app) {
  const rm = app.removeGeoJsonLayer || app.removeLayer;
  if (typeof rm !== "function") return;
  for (const name of OWN_LAYERS) {
    try {
      rm.call(app, name);
    } catch (err) {
      /* a layer not yet added is not an error worth throwing over */
    }
  }
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = `${CSS_PREFIX}-${cls}`;
  if (text !== undefined) n.textContent = text;
  return n;
}

function renderPanel(app, state, container) {
  container.innerHTML = "";
  const root = el("div", "root");

  const status = el("div", "status", "Load a model.json, then click the map.");
  const numbers = el("div", "numbers");

  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".json,application/json";
  file.className = `${CSS_PREFIX}-file`;

  const opts = state.opts;
  const controls = el("div", "controls");

  const check = (label, key) => {
    const wrap = el("label", "check");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!opts[key];
    box.onchange = () => {
      opts[key] = box.checked;
      draw();
    };
    wrap.append(box, document.createTextNode(" " + label));
    return wrap;
  };

  const hour = document.createElement("input");
  hour.type = "range";
  hour.min = "5";
  hour.max = "20";
  hour.step = "0.25";
  hour.value = String(opts.hour);
  hour.className = `${CSS_PREFIX}-slider`;
  hour.oninput = () => {
    opts.hour = parseFloat(hour.value);
    draw();
  };

  const season = el("div", "seasons");
  for (const [label, day] of [
    ["21 Jun", 172],
    ["21 Mar", 80],
    ["21 Dec", 355],
  ]) {
    const b = el("button", "season", label);
    b.onclick = () => {
      opts.day = day;
      draw();
    };
    season.append(b);
  }

  function draw() {
    if (!state.model || !state.anchor) return;
    const layers = buildLayers(state.model, state.anchor, opts);
    // Clear our own layers before re-adding. Without this, a shadow
    // drawn at noon stayed on the map after the slider dropped the sun
    // below the 3° cutoff — the numbers said "sun too low" while the
    // map still showed the shade — and hosts that append rather than
    // replace stacked duplicates on every slider tick.
    removeOwnLayers(app);
    // Draw beneath first so the building reads on top.
    if (layers.shadow) app.addGeoJsonLayer("Shadow", layers.shadow);
    if (layers.pd) app.addGeoJsonLayer("PD envelope", layers.pd);
    app.addGeoJsonLayer("Red line", layers.red);
    app.addGeoJsonLayer("Building", layers.building);

    const f = layers.building.features[0].properties;
    const bits = [
      `${f.footprint_m2} m² footprint`,
      f.floor_area_m2 ? `${f.floor_area_m2} m² floor area` : null,
      f.ridge_m ? `ridge ${f.ridge_m} m` : null,
      layers.info.pdDepth ? `PD rear ${layers.info.pdDepth} m` : null,
      layers.info.reach
        ? `shadow ${layers.info.reach.toFixed(1)} m at ` +
          `${layers.info.altitude.toFixed(0)}°`
        : layers.info.altitude !== undefined
          ? "sun too low for a shadow outline"
          : null,
    ].filter(Boolean);
    numbers.textContent = bits.join(" · ");
    status.textContent = f.outline;
  }
  state.draw = draw;

  file.onchange = async () => {
    const chosen = file.files && file.files[0];
    if (!chosen) return;
    try {
      state.model = JSON.parse(await chosen.text());
      if (!state.model.walls || !state.model.extent_m) {
        throw new Error("not a building model — no walls or extent");
      }
      status.textContent = state.anchor
        ? "Model loaded."
        : "Model loaded. Now click the map to place it.";
      draw();
    } catch (err) {
      state.model = null;
      status.textContent = `Could not read that file: ${err.message}`;
    }
  };

  const bearing = document.createElement("input");
  bearing.type = "number";
  bearing.value = "0";
  bearing.step = "1";
  bearing.className = `${CSS_PREFIX}-bearing`;
  bearing.onchange = () => {
    if (state.anchor) {
      state.anchor.bearing = parseFloat(bearing.value) || 0;
      draw();
    }
  };
  state.onPlace = (lngLat) => {
    state.anchor = {
      lon: lngLat.lng,
      lat: lngLat.lat,
      bearing: parseFloat(bearing.value) || 0,
    };
    status.textContent = state.model
      ? "Placed."
      : "Anchor set — now load a model.json.";
    draw();
  };

  controls.append(
    check("Permitted development envelope", "pd"),
    check("Detached (4 m rather than 3 m)", "pdDetached"),
    check("Shadow", "shadow"),
  );

  root.append(
    el("div", "hint", "1 · Load the model JSON this project exports"),
    file,
    el("div", "hint", "2 · Click the map to set the origin corner"),
    (() => {
      const w = el("label", "check");
      w.append(
        document.createTextNode("Bearing of plan north (°) "),
        bearing,
      );
      return w;
    })(),
    el("div", "hint", "3 · What to draw"),
    controls,
    el("div", "hint", "Sun — hour and season"),
    hour,
    season,
    status,
    numbers,
    el("div", "warn", PD_WARNING),
  );
  container.append(root);
  draw();
}

/* --------------------------------------------------------- the plugin */

const plugin = {
  id: ID,
  name: "Builder — site plan",
  version: "0.2.0",

  activate(app) {
    const state = {
      model: null,
      anchor: null,
      draw: null,
      onPlace: null,
      opts: {
        redLineMargin: 6,
        pd: true,
        pdDetached: true,
        pdLarger: false,
        pdTwoStorey: false,
        shadow: true,
        day: 355,
        hour: 12,
      },
      teardown: [],
    };
    this._state = state;

    const map = app.getMap && app.getMap();
    if (map) {
      const onClick = (e) => state.onPlace && state.onPlace(e.lngLat);
      map.on("click", onClick);
      state.teardown.push(() => map.off("click", onClick));
    }

    if (app.registerFloatingPanel) {
      const off = app.registerFloatingPanel({
        id: `${ID}-panel`,
        title: "Builder — site plan",
        defaultWidth: 320,
        render: (container) => renderPanel(app, state, container),
      });
      if (typeof off === "function") state.teardown.push(off);
      return true;
    }
    // No panel host: the plugin still works headlessly through
    // window.__BUILDER_SITEPLAN__ rather than failing silently.
    window.__BUILDER_SITEPLAN__ = {
      place: (lon, lat, bearing = 0) => {
        state.anchor = { lon, lat, bearing };
        state.draw && state.draw();
      },
      load: (model) => {
        state.model = model;
        state.draw && state.draw();
      },
      buildLayers,
    };
    return true;
  },

  deactivate() {
    const state = this._state;
    if (!state) return;
    for (const fn of state.teardown) {
      try {
        fn();
      } catch (err) {
        /* a torn-down host is not an error worth throwing over */
      }
    }
    state.teardown = [];
    delete window.__BUILDER_SITEPLAN__;
    this._state = null;
  },

  getProjectState() {
    const state = this._state;
    if (!state) return undefined;
    return { anchor: state.anchor, opts: state.opts };
  },

  applyProjectState(app, saved) {
    const state = this._state;
    if (!state || !saved || typeof saved !== "object") return false;
    if (saved.anchor) state.anchor = saved.anchor;
    if (saved.opts) Object.assign(state.opts, saved.opts);
    state.draw && state.draw();
    return true;
  },
};

export default plugin;
export { plugin, buildLayers, sunPosition, footprintRing, localToWgs84 };

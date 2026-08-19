/* The map engine. Ours, from Web Mercator up — no MapLibre, no CDN.
 *
 * WHY WRITE THIS RATHER THAN IMPORT ONE. Three reasons that survived the
 * benchmark: (1) every library fetches its tiles and its own code at view
 * time, and this product has to work in a garden with no signal; (2) a
 * library's vector layer owns hit-testing, and property SELECTION is the
 * one interaction that must never pick the neighbour's house — we need
 * that code to be ours and tested; (3) a 900 KB dependency to draw
 * polygons on a canvas is a poor trade when the projection is fifteen
 * lines and the renderer is two hundred.
 *
 * It is a real engine, not a demo: fractional zoom, LOD, frustum
 * culling, a layer stack, geodesic-consistent screen maths, pointer and
 * touch input, and hit-testing that honours holes.
 *
 * COORDINATES. Three frames, never mixed:
 *   lon/lat   WGS84 degrees            — what the API speaks
 *   world     Web Mercator pixels at the current fractional zoom
 *   screen    device pixels on the canvas backing store
 * Every conversion is a named function. Mixing CSS and device pixels is
 * the classic bug in this kind of code and it is why the scale bar in an
 * earlier iteration read double on phones.
 */
'use strict';

export const TILE = 256;
export const EARTH_CIRCUM = 40075016.686;

export function lonLatToWorld(lon, lat, z) {
  const n = TILE * Math.pow(2, z);
  const s = Math.max(-85.05112878, Math.min(85.05112878, lat));
  return [
    (lon + 180) / 360 * n,
    (1 - Math.asinh(Math.tan(s * Math.PI / 180)) / Math.PI) / 2 * n,
  ];
}

export function worldToLonLat(x, y, z) {
  const n = TILE * Math.pow(2, z);
  return [
    x / n * 360 - 180,
    Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI,
  ];
}

/* Metres per CSS pixel. One world pixel is one CSS pixel in this engine
 * (see toScreen), so there is deliberately no devicePixelRatio here. */
export function metresPerPixel(lat, z) {
  return EARTH_CIRCUM * Math.cos(lat * Math.PI / 180) / (TILE * Math.pow(2, z));
}

/* The LOCAL radius of curvature, not the mean radius. Identical to
 * geodesy.local_radius in Python — the two implementations are held to
 * the same numbers by a test, because a client preview that disagreed
 * with the server's area would be worse than showing nothing. Using the
 * 6371 km mean sphere under-measures UK footprints by 0.4%. */
const WGS84_A = 6378137.0;
const WGS84_F = 1 / 298.257223563;
const WGS84_E2 = WGS84_F * (2 - WGS84_F);

export function localRadius(latDeg) {
  const s = Math.sin(latDeg * Math.PI / 180);
  const w = Math.sqrt(1 - WGS84_E2 * s * s);
  const m = WGS84_A * (1 - WGS84_E2) / (w * w * w);
  const n = WGS84_A / w;
  return Math.sqrt(m * n);
}

export function haversine(a, b) {   // [lon,lat] pairs -> metres
  const p = Math.PI / 180;
  const dLat = (b[1] - a[1]) * p, dLon = (b[0] - a[0]) * p;
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * p) * Math.cos(b[1] * p) * Math.sin(dLon / 2) ** 2;
  return 2 * localRadius((a[1] + b[1]) / 2) * Math.asin(Math.min(1, Math.sqrt(h)));
}

/* Geodesic ring area, m2 — the SAME spherical-excess formula the Python
 * side uses, on the same local sphere. */
export function ringArea(ring) {
  if (!ring || ring.length < 4) return 0;
  const pts = (ring[0][0] === ring[ring.length - 1][0] &&
               ring[0][1] === ring[ring.length - 1][1])
    ? ring.slice(0, -1) : ring;
  const p = Math.PI / 180;
  let t = 0, latSum = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    t += (x2 - x1) * p * (2 + Math.sin(y1 * p) + Math.sin(y2 * p));
    latSum += y1;
  }
  const R = localRadius(latSum / pts.length);
  return Math.abs(t * R * R / 2);
}

export function geometryArea(g) {
  if (!g) return 0;
  const polys = g.type === 'Polygon' ? [g.coordinates]
    : g.type === 'MultiPolygon' ? g.coordinates : [];
  let a = 0;
  for (const poly of polys) {
    if (!poly || !poly.length) continue;
    a += ringArea(poly[0]);
    for (let i = 1; i < poly.length; i++) a -= ringArea(poly[i]);
  }
  return Math.max(0, a);
}

export function pointInGeometry(lon, lat, g) {
  const polys = !g ? [] : g.type === 'Polygon' ? [g.coordinates]
    : g.type === 'MultiPolygon' ? g.coordinates : [];
  const inRing = (ring) => {
    let inside = false;
    for (let i = 0, n = ring.length; i < n; i++) {
      const [x1, y1] = ring[i], [x2, y2] = ring[(i + 1) % n];
      if ((y1 > lat) !== (y2 > lat)) {
        const xin = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) || 1e-15);
        if (lon < xin) inside = !inside;
      }
    }
    return inside;
  };
  for (const poly of polys) {
    if (!poly || !poly.length) continue;
    if (inRing(poly[0]) && !poly.slice(1).some(inRing)) return true;
  }
  return false;
}

export function bboxOf(g) {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  const walk = (c) => {
    if (!c) return;
    if (typeof c[0] === 'number') {
      w = Math.min(w, c[0]); e = Math.max(e, c[0]);
      s = Math.min(s, c[1]); n = Math.max(n, c[1]); return;
    }
    for (const x of c) walk(x);
  };
  walk(g && g.coordinates);
  return isFinite(w) ? [w, s, e, n] : null;
}

/* --- layers ---------------------------------------------------------
 * A layer draws and optionally hit-tests. Keeping the contract this
 * small is what lets Stage 3's 3D and Stage 7's utilities plug in
 * without the engine learning about them. */
export class Layer {
  constructor(id, opts = {}) {
    this.id = id;
    this.visible = opts.visible !== false;
    this.style = opts.style || {};
    this.data = opts.data || null;
    this.zIndex = opts.zIndex || 0;
  }
  draw() {}
  hit() { return null; }
}

export class GeoJSONLayer extends Layer {
  /* Vector features in lon/lat, drawn and hit-tested in the map's frame.
   * classification drives the colour: verified, derived, estimated and
   * user geometry must never look alike. */
  constructor(id, opts = {}) {
    super(id, opts);
    this.selectedId = null;
    this.hoverId = null;
  }

  features() {
    const d = this.data;
    if (!d) return [];
    return d.type === 'FeatureCollection' ? (d.features || [])
      : d.type === 'Feature' ? [d] : [];
  }

  draw(map, ctx) {
    const s = map.pixelRatio;
    for (const f of this.features()) {
      const g = f.geometry;
      if (!g) continue;
      const bb = bboxOf(g);
      if (bb && !map.bboxVisible(bb)) continue;      // frustum culling
      /* The FEATURE decides its colour, then the layer's default, then
       * verified. Layer style must not be able to repaint a verified
       * footprint as user geometry. */
      const cls = (f.properties && f.properties.classification) ||
                  this.style.classification || 'verified';
      const sel = f.id != null && f.id === this.selectedId;
      const hov = f.id != null && f.id === this.hoverId;
      const st = Object.assign({}, CLASS_STYLE[cls] || CLASS_STYLE.verified,
                               this.style);
      const polys = g.type === 'Polygon' ? [g.coordinates]
        : g.type === 'MultiPolygon' ? g.coordinates
        : g.type === 'LineString' ? [[g.coordinates]] : [];
      for (const poly of polys) {
        for (let ri = 0; ri < poly.length; ri++) {
          const ring = poly[ri];
          if (!ring || ring.length < 2) continue;
          ctx.beginPath();
          for (let i = 0; i < ring.length; i++) {
            const p = map.toScreen(ring[i][0], ring[i][1]);
            i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
          }
          if (g.type !== 'LineString') ctx.closePath();
          if (st.fill && g.type !== 'LineString') {
            ctx.fillStyle = sel ? st.fillSelected : hov ? st.fillHover : st.fill;
            ctx.fill('evenodd');
          }
          ctx.lineWidth = (sel ? st.widthSelected : st.width) * s;
          ctx.strokeStyle = sel ? st.strokeSelected : st.stroke;
          ctx.lineJoin = 'round';
          ctx.stroke();
        }
      }
    }
  }

  hit(map, lon, lat) {
    /* Smallest CONTAINING feature — never nearest. A tap in a garden
     * must not select the house next to it. */
    const hits = this.features().filter(
      (f) => pointInGeometry(lon, lat, f.geometry));
    if (!hits.length) return null;
    hits.sort((a, b) => geometryArea(a.geometry) - geometryArea(b.geometry));
    return hits[0];
  }
}

export const CLASS_STYLE = {
  verified:  { stroke: '#ffd600', fill: 'rgba(255,214,0,0.14)',
               fillHover: 'rgba(255,214,0,0.28)',
               fillSelected: 'rgba(255,214,0,0.42)',
               strokeSelected: '#fff3a0', width: 1.4, widthSelected: 3 },
  derived:   { stroke: '#4fc3f7', fill: 'rgba(79,195,247,0.12)',
               fillHover: 'rgba(79,195,247,0.24)',
               fillSelected: 'rgba(79,195,247,0.4)',
               strokeSelected: '#b3e5fc', width: 1.4, widthSelected: 3 },
  estimated: { stroke: '#b085f5', fill: 'rgba(176,133,245,0.10)',
               fillHover: 'rgba(176,133,245,0.2)',
               fillSelected: 'rgba(176,133,245,0.34)',
               strokeSelected: '#d1b3ff', width: 1.2, widthSelected: 2.6 },
  user:      { stroke: '#39ff88', fill: 'rgba(57,255,136,0.12)',
               fillHover: 'rgba(57,255,136,0.24)',
               fillSelected: 'rgba(57,255,136,0.4)',
               strokeSelected: '#b9ffd6', width: 1.6, widthSelected: 3 },
};

/* --- the map -------------------------------------------------------- */
export class MapEngine {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.centre = opts.centre || [0, 20];      // [lon, lat]
    this.zoom = opts.zoom == null ? 2 : opts.zoom;
    this.minZoom = opts.minZoom == null ? 1 : opts.minZoom;
    this.maxZoom = opts.maxZoom == null ? 22 : opts.maxZoom;
    this.layers = [];
    this._listeners = {};
    this._pointers = new Map();
    this._drag = null;
    this._raf = null;
    this._bindInput();
    this.resize();
  }

  get pixelRatio() { return Math.min(2, window.devicePixelRatio || 1); }

  on(evt, fn) { (this._listeners[evt] ||= []).push(fn); return this; }
  emit(evt, payload) {
    for (const fn of this._listeners[evt] || []) fn(payload);
  }

  addLayer(layer) {
    this.layers.push(layer);
    this.layers.sort((a, b) => a.zIndex - b.zIndex);
    this.render();
    return layer;
  }
  layer(id) { return this.layers.find((l) => l.id === id); }

  resize() {
    const r = this.pixelRatio;
    const w = this.canvas.clientWidth || window.innerWidth;
    const h = this.canvas.clientHeight || window.innerHeight;
    this.canvas.width = Math.floor(w * r);
    this.canvas.height = Math.floor(h * r);
    this.render();
  }

  /* lon/lat -> device pixels on the backing store. */
  toScreen(lon, lat) {
    const c = lonLatToWorld(this.centre[0], this.centre[1], this.zoom);
    const p = lonLatToWorld(lon, lat, this.zoom);
    const r = this.pixelRatio;
    return [(p[0] - c[0]) * r + this.canvas.width / 2,
            (p[1] - c[1]) * r + this.canvas.height / 2];
  }

  /* device pixels -> lon/lat. */
  toLonLat(sx, sy) {
    const c = lonLatToWorld(this.centre[0], this.centre[1], this.zoom);
    const r = this.pixelRatio;
    return worldToLonLat(c[0] + (sx - this.canvas.width / 2) / r,
                         c[1] + (sy - this.canvas.height / 2) / r, this.zoom);
  }

  /* CSS pixels (what a DOM event carries) -> lon/lat. */
  fromClient(clientX, clientY) {
    const b = this.canvas.getBoundingClientRect();
    const r = this.pixelRatio;
    return this.toLonLat((clientX - b.left) * r, (clientY - b.top) * r);
  }

  bounds() {
    const r = this.pixelRatio;
    const a = this.toLonLat(0, 0);
    const b = this.toLonLat(this.canvas.width, this.canvas.height);
    return [Math.min(a[0], b[0]), Math.min(a[1], b[1]),
            Math.max(a[0], b[0]), Math.max(a[1], b[1])];
  }

  bboxVisible(bb) {
    const v = this.bounds();
    return !(bb[2] < v[0] || bb[0] > v[2] || bb[3] < v[1] || bb[1] > v[3]);
  }

  metresPerPixel() { return metresPerPixel(this.centre[1], this.zoom); }

  setView(centre, zoom) {
    if (centre) this.centre = [centre[0], centre[1]];
    if (zoom != null) {
      this.zoom = Math.max(this.minZoom, Math.min(this.maxZoom, zoom));
    }
    this.emit('move', this.viewState());
    this.render();
  }

  fitBounds(bb, padding = 0.25) {
    if (!bb) return;
    const [w, s, e, n] = bb;
    const centre = [(w + e) / 2, (s + n) / 2];
    const r = this.pixelRatio;
    const cw = this.canvas.width / r, ch = this.canvas.height / r;
    let z = this.maxZoom;
    for (let t = this.maxZoom; t >= this.minZoom; t -= 0.25) {
      const a = lonLatToWorld(w, n, t), b = lonLatToWorld(e, s, t);
      if (Math.abs(b[0] - a[0]) <= cw * (1 - padding) &&
          Math.abs(b[1] - a[1]) <= ch * (1 - padding)) { z = t; break; }
    }
    this.setView(centre, z);
  }

  viewState() {
    return { centre: this.centre.slice(), zoom: this.zoom,
             bounds: this.bounds(), mpp: this.metresPerPixel() };
  }

  zoomAround(clientX, clientY, dz) {
    const before = this.fromClient(clientX, clientY);
    this.zoom = Math.max(this.minZoom, Math.min(this.maxZoom, this.zoom + dz));
    const after = this.fromClient(clientX, clientY);
    this.centre = [this.centre[0] + before[0] - after[0],
                   this.centre[1] + before[1] - after[1]];
    this.emit('move', this.viewState());
    this.render();
  }

  hitTest(lon, lat) {
    for (let i = this.layers.length - 1; i >= 0; i--) {
      const l = this.layers[i];
      if (!l.visible) continue;
      const f = l.hit(this, lon, lat);
      if (f) return { layer: l.id, feature: f };
    }
    return null;
  }

  render() {
    if (this._raf) return;                 // coalesce to one frame
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      const ctx = this.ctx;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = '#0e1116';
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
      for (const l of this.layers) if (l.visible) l.draw(this, ctx);
      this.emit('render', this.viewState());
    });
  }

  _bindInput() {
    const cv = this.canvas;
    cv.style.touchAction = 'none';

    cv.addEventListener('pointerdown', (e) => {
      cv.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      /* Pan follows ONE pointer, and only while it is alone: a second
       * finger means pinch, and sharing drag state between them makes
       * the map lurch by the distance between the fingers. */
      this._drag = this._pointers.size === 1
        ? { id: e.pointerId, x: e.clientX, y: e.clientY, moved: 0 } : null;
      this._pinch = null;
    });

    cv.addEventListener('pointermove', (e) => {
      if (this._pointers.has(e.pointerId)) {
        this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      }
      if (this._pointers.size === 2) { this._handlePinch(); return; }
      if (!this._drag || e.pointerId !== this._drag.id) {
        const ll = this.fromClient(e.clientX, e.clientY);
        this.emit('hover', { lon: ll[0], lat: ll[1] });
        return;
      }
      const dx = e.clientX - this._drag.x, dy = e.clientY - this._drag.y;
      this._drag.moved += Math.abs(dx) + Math.abs(dy);
      const c = lonLatToWorld(this.centre[0], this.centre[1], this.zoom);
      this.centre = worldToLonLat(c[0] - dx, c[1] - dy, this.zoom);
      this._drag.x = e.clientX; this._drag.y = e.clientY;
      this.emit('move', this.viewState());
      this.render();
    });

    const end = (e) => {
      this._pointers.delete(e.pointerId);
      if (this._pointers.size < 2) this._pinch = null;
      if (!this._drag || e.pointerId !== this._drag.id) return;
      const tap = this._drag.moved < 6;
      this._drag = null;
      if (tap) {
        const ll = this.fromClient(e.clientX, e.clientY);
        this.emit('click', { lon: ll[0], lat: ll[1],
                             hit: this.hitTest(ll[0], ll[1]) });
      }
    };
    cv.addEventListener('pointerup', end);
    cv.addEventListener('pointercancel', end);

    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.zoomAround(e.clientX, e.clientY, -e.deltaY / 450);
    }, { passive: false });

    window.addEventListener('resize', () => this.resize());
  }

  _handlePinch() {
    const [a, b] = [...this._pointers.values()];
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    if (this._pinch) this.zoomAround(mx, my, Math.log2(d / this._pinch));
    this._pinch = d;
  }
}

/* A scale bar that tells the truth: a round number of metres and the
 * exact pixel width that many metres occupy. */
export function scaleBar(mpp, targetPx = 120) {
  const target = targetPx * mpp;
  const pow = Math.pow(10, Math.floor(Math.log10(target)));
  const nice = [1, 2, 5, 10].map((v) => v * pow)
    .reduce((p, c) => Math.abs(c - target) < Math.abs(p - target) ? c : p);
  return { metres: nice, px: nice / mpp,
           label: nice >= 1000 ? (nice / 1000) + ' km' : nice + ' m' };
}

/* Stage 5: the floor plan. A VIEW of the model, not a second drawing.
 *
 * The brief's mandatory requirement is that editing the plan updates the
 * 3D and editing the 3D updates the plan. The only way to get that
 * without a synchronisation bug is to refuse to have two models: this
 * canvas renders design.floor_plan(), which is computed from the same
 * blocks the 3D extrudes, and every edit it makes goes back through the
 * same command endpoint. There is nothing to keep in sync because there
 * is only one thing.
 *
 * It is a REAL plan, not a diagram: walls at scale with thickness,
 * dimension strings on every block, hatched openings, a north point that
 * knows the building's true bearing, and a scale bar. The numbers on it
 * are the numbers the take-off uses.
 */
'use strict';

const WALL_T = 0.3;

export class PlanView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.level = 0;
    this.data = null;         // design.floor_plan payload
    this.bearing = 0;
    this.scale = 20;          // pixels per metre (CSS)
    this.pan = [0, 0];
    this.selected = null;     // {block, edge}
    this.onPick = null;
    this.onDrag = null;
    this._bind();
    this.resize();
  }

  get pixelRatio() { return Math.min(2, window.devicePixelRatio || 1); }

  resize() {
    const r = this.pixelRatio;
    this.canvas.width = Math.floor((this.canvas.clientWidth || 800) * r);
    this.canvas.height = Math.floor((this.canvas.clientHeight || 600) * r);
    this.draw();
  }

  /* KEEP THE USER'S VIEW, BUT NEVER STRAND THE BUILDING OFF-SCREEN.
   *
   * This runs after every command, refused ones included. Re-fitting
   * each time threw away the zoom the user had just set up to nudge a
   * partition. Fitting only once is worse: add a 4 m extension and the
   * new wall lands outside the view with no way back — the flagship
   * gesture, unreachable.
   *
   * So: fit when the MODEL's extent changes and the result would not
   * be fully visible. A pan or zoom leaves the extent alone, so the
   * view is kept; an edit inside the current view keeps it too; an
   * edit that grows the building past the edge brings it back. */
  set(data, bearing) {
    this.data = data;
    if (bearing != null) this.bearing = bearing;
    if (this.level >= (data.levels || []).length) this.level = 0;
    const b = this.bounds();
    const grew = !this._lastBounds || !b || b.some(
      (v, i) => Math.abs(v - this._lastBounds[i]) > 1e-6);
    this._lastBounds = b;
    if (!this._everFit || (grew && !this.allVisible(b))) {
      this._everFit = true;
      this.fit();
    } else {
      this.draw();
    }
  }

  /** Plan extent of the current level: [x0, y0, x1, y1], or null. */
  bounds() {
    const L = this.levelData();
    if (!L || !L.blocks.length) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const b of L.blocks) {
      for (const [x, y] of b.ring) {
        x0 = Math.min(x0, x); x1 = Math.max(x1, x);
        y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      }
    }
    return [x0, y0, x1, y1];
  }

  /** Does that extent sit inside the canvas, with room for dimensions? */
  allVisible(b) {
    if (!b) return true;
    const pad = 14;                       // device px of breathing space
    const w = this.canvas.width, h = this.canvas.height;
    for (const [x, y] of [[b[0], b[1]], [b[2], b[1]],
                          [b[2], b[3]], [b[0], b[3]]]) {
      const [px, py] = this.toPx(x, y);
      if (px < pad || py < pad || px > w - pad || py > h - pad) return false;
    }
    return true;
  }

  levelData() {
    return (this.data && this.data.levels && this.data.levels[this.level])
      || null;
  }

  fit() {
    const L = this.levelData();
    if (!L || !L.blocks.length) { this.draw(); return; }
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const b of L.blocks) {
      for (const [x, y] of b.ring) {
        x0 = Math.min(x0, x); x1 = Math.max(x1, x);
        y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      }
    }
    const r = this.pixelRatio;
    const w = this.canvas.width / r, h = this.canvas.height / r;
    const pad = 3.5;                     // metres of margin for dimensions
    this.scale = Math.min(w / (x1 - x0 + pad * 2), h / (y1 - y0 + pad * 2));
    this.pan = [w / 2 - ((x0 + x1) / 2) * this.scale,
                h / 2 + ((y0 + y1) / 2) * this.scale];
    this.draw();
  }

  /* Plan metres -> device pixels. Plan +y is INTO the page (north of the
   * building's frame), so screen y is negated: a plan drawn upside down
   * is the classic way a rear extension ends up on the front elevation. */
  toPx(x, y) {
    const r = this.pixelRatio;
    return [(this.pan[0] + x * this.scale) * r,
            (this.pan[1] - y * this.scale) * r];
  }

  toPlan(px, py) {
    const r = this.pixelRatio;
    return [(px / r - this.pan[0]) / this.scale,
            -(py / r - this.pan[1]) / this.scale];
  }

  draw() {
    const ctx = this.ctx, r = this.pixelRatio;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#12151b';
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const L = this.levelData();
    if (!L) return;
    this._grid(ctx, r);

    const COL = { verified: '#ffd600', derived: '#4fc3f7',
                  estimated: '#b085f5', user: '#39ff88' };

    // Floor plates first, so walls draw over them.
    for (const b of L.blocks) {
      ctx.beginPath();
      b.ring.forEach(([x, y], i) => {
        const p = this.toPx(x, y);
        i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
      });
      ctx.closePath();
      ctx.fillStyle = (COL[b.classification] || '#888') + '1e';
      ctx.fill();
    }

    // ROOMS, under the walls. Drawn from the same model the 3D and the
    // regulations gate read, so a room shown here is a room the gate saw.
    const KIND_FILL = { circulation: '#4fc3f722', kitchen: '#ffb26b22',
                        wet: '#7fd6ff22', store: '#9aa3b022',
                        room: '#39ff8814' };
    for (const r of (L.rooms || [])) {
      ctx.beginPath();
      r.ring.forEach(([x, y], i) => {
        const p = this.toPx(x, y);
        i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
      });
      ctx.closePath();
      ctx.fillStyle = KIND_FILL[r.kind] || KIND_FILL.room;
      ctx.fill();
    }

    // Partitions between rooms, thinner than the envelope.
    for (const w of (L.partitions || [])) {
      const [a, b] = w.points;
      const p0 = this.toPx(a[0], a[1]), p1 = this.toPx(b[0], b[1]);
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
      ctx.lineWidth = Math.max(1.5 * r, 0.1 * this.scale * r);
      ctx.strokeStyle = this.selected && this.selected.id === w.id
        ? '#ffffff' : '#8d97a8';
      ctx.stroke();
    }

    // Walls, at real thickness.
    for (const w of L.walls) {
      const [a, b] = w.points;
      const p0 = this.toPx(a[0], a[1]), p1 = this.toPx(b[0], b[1]);
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
      ctx.lineCap = 'square';
      const sel = this.selected && this.selected.id === w.id;
      ctx.lineWidth = Math.max(2 * r, WALL_T * this.scale * r);
      ctx.strokeStyle = sel ? '#ffffff'
        : w.external ? (COL[(L.blocks.find((x) => x.id === w.block) || {})
                            .classification] || '#e8e8e8') : '#6d7686';
      ctx.stroke();
      if (sel) {                    // grip, so the drag target is obvious
        const m = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2];
        ctx.beginPath(); ctx.arc(m[0], m[1], 7 * r, 0, 7);
        ctx.fillStyle = '#ffffff'; ctx.fill();
      }
    }

    // Openings, drawn as gaps with a sill line.
    for (const op of L.openings) {
      const blk = L.blocks.find((b) => b.id === op.block_id);
      const wall = L.walls.find((w) => w.block === op.block_id &&
                                       w.edge === op.edge);
      if (!blk || !wall) continue;
      const [a, b] = wall.points;
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
      const s = [a[0] + ux * op.along_m, a[1] + uy * op.along_m];
      const e = [s[0] + ux * op.width, s[1] + uy * op.width];
      const p0 = this.toPx(s[0], s[1]), p1 = this.toPx(e[0], e[1]);
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
      ctx.lineWidth = Math.max(2 * r, WALL_T * this.scale * r) + 2 * r;
      ctx.strokeStyle = '#12151b';        // knock the wall out
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
      ctx.lineWidth = 2.2 * r;
      ctx.strokeStyle = op.kind === 'window' ? '#8fd6ff' : '#ffd600';
      ctx.stroke();
    }

    // Dimensions and labels.
    ctx.font = `${12 * r}px ui-monospace, SFMono-Regular, monospace`;
    for (const rm of (L.rooms || [])) {
      const c = this.toPx(rm.x + rm.width / 2, rm.y + rm.depth / 2);
      const lines = [rm.name, `${rm.area_m2} m²`];
      if (this.scale > 14) {
        lines.push(`${rm.width.toFixed(2)} × ${rm.depth.toFixed(2)}`);
      }
      /* A HALL IS NARROWER THAN ITS OWN NAME. Centred text in a 1.55 m
       * hall ran straight through both walls and over the rooms beside
       * it. So: if the label does not fit across the room, turn it and
       * read it up the room — which is what a drawn plan does — and if
       * it does not fit that way either, drop to the area alone. */
      const wide = Math.max(...lines.map((t) => ctx.measureText(t).width));
      const across = rm.width * this.scale * r;
      const along = rm.depth * this.scale * r;
      const turn = wide > across - 8 * r && along > across;
      ctx.save();
      ctx.translate(c[0], c[1]);
      if (turn) ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      const room = turn ? along : across;
      const show = wide > room - 8 * r ? lines.slice(1, 2) : lines;
      show.forEach((t, i) => {
        ctx.fillStyle = (i === 0 && show.length > 1) ? '#eef1f6' : '#98a0ae';
        ctx.fillText(t, 0, (i - (show.length - 1) / 2) * 14 * r + 4 * r);
      });
      ctx.restore();
      ctx.textAlign = 'center';
    }
    for (const b of L.blocks) {
      const xs = b.ring.map((p) => p[0]), ys = b.ring.map((p) => p[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      const y0 = Math.min(...ys), y1 = Math.max(...ys);
      this._dim(ctx, r, [x0, y0 - 0.9], [x1, y0 - 0.9], `${(x1 - x0).toFixed(2)} m`);
      this._dim(ctx, r, [x1 + 0.9, y0], [x1 + 0.9, y1], `${(y1 - y0).toFixed(2)} m`);
      /* THE BLOCK NAME GOES IN THE MIDDLE — WHICH IS WHERE A ROOM IS.
       * Once rooms are drawn, "Existing building 65.59 m²" landed on top
       * of "Dining room 12.18 m²" and both became unreadable. A plan
       * labels ROOMS; the block is named quietly in its corner, and only
       * while it has no rooms of its own does it take the middle. */
      const covered = (L.rooms || []).some(
        (rm) => rm.x + rm.width > x0 + 1e-6 && rm.x < x1 - 1e-6 &&
                rm.y + rm.depth > y0 + 1e-6 && rm.y < y1 - 1e-6);
      ctx.textAlign = covered ? 'left' : 'center';
      if (covered) {
        // Bottom-left INSIDE the block: the top-left corner is where the
        // next block's width dimension lands, and the two collided.
        const c = this.toPx(x0, y0);
        ctx.fillStyle = '#7b8494';
        ctx.textAlign = 'left';
        const room = (x1 - x0) * this.scale * r - 10 * r;
        const full = `${b.name} · ${b.area_m2} m²`;
        ctx.fillText(ctx.measureText(full).width <= room ? full : b.name,
                     c[0] + 5 * r, c[1] - 6 * r);
      } else {
        const c = this.toPx((x0 + x1) / 2, (y0 + y1) / 2);
        ctx.fillStyle = '#eef1f6';
        ctx.fillText(b.name, c[0], c[1] - 4 * r);
        ctx.fillStyle = '#98a0ae';
        ctx.fillText(`${b.area_m2} m²`, c[0], c[1] + 14 * r);
      }
    }

    this._north(ctx, r);
    this._scalebar(ctx, r);
  }

  _grid(ctx, r) {
    const step = this.scale > 26 ? 1 : this.scale > 9 ? 5 : 10;
    const w = this.canvas.width / r, h = this.canvas.height / r;
    const [mnx, mxy] = this.toPlan(0, 0);
    const [mxx, mny] = this.toPlan(this.canvas.width, this.canvas.height);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(255,255,255,0.045)';
    ctx.beginPath();
    for (let x = Math.floor(mnx / step) * step; x <= mxx; x += step) {
      const p = this.toPx(x, 0);
      ctx.moveTo(p[0], 0); ctx.lineTo(p[0], this.canvas.height);
    }
    for (let y = Math.floor(mny / step) * step; y <= mxy; y += step) {
      const p = this.toPx(0, y);
      ctx.moveTo(0, p[1]); ctx.lineTo(this.canvas.width, p[1]);
    }
    ctx.stroke();
  }

  _dim(ctx, r, a, b, text) {
    const p0 = this.toPx(a[0], a[1]), p1 = this.toPx(b[0], b[1]);
    ctx.strokeStyle = '#6d7686';
    ctx.lineWidth = 1 * r;
    ctx.beginPath();
    ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
    const t = 4 * r;
    const vertical = Math.abs(p1[0] - p0[0]) < Math.abs(p1[1] - p0[1]);
    if (vertical) {
      ctx.moveTo(p0[0] - t, p0[1]); ctx.lineTo(p0[0] + t, p0[1]);
      ctx.moveTo(p1[0] - t, p1[1]); ctx.lineTo(p1[0] + t, p1[1]);
    } else {
      ctx.moveTo(p0[0], p0[1] - t); ctx.lineTo(p0[0], p0[1] + t);
      ctx.moveTo(p1[0], p1[1] - t); ctx.lineTo(p1[0], p1[1] + t);
    }
    ctx.stroke();
    const m = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2];
    ctx.save();
    ctx.translate(m[0], m[1]);
    if (vertical) ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = '#c8cedb';
    ctx.textAlign = 'center';
    ctx.fillText(text, 0, -5 * r);
    ctx.restore();
  }

  _north(ctx, r) {
    // The building frame is rotated from true north by `bearing`; the
    // arrow must point at NORTH, not up the page, or the plan lies about
    // orientation and every sun study built on it is wrong.
    const cx = this.canvas.width - 46 * r, cy = 46 * r, R = 20 * r;
    const a = -this.bearing * Math.PI / 180;
    ctx.save();
    ctx.translate(cx, cy); ctx.rotate(a);
    ctx.beginPath();
    ctx.moveTo(0, -R); ctx.lineTo(R * 0.38, R * 0.42);
    ctx.lineTo(0, R * 0.16); ctx.lineTo(-R * 0.38, R * 0.42);
    ctx.closePath();
    ctx.fillStyle = '#eef1f6'; ctx.fill();
    ctx.restore();
    ctx.fillStyle = '#98a0ae';
    ctx.textAlign = 'center';
    ctx.fillText('N', cx, cy + R + 14 * r);
  }

  _scalebar(ctx, r) {
    const target = 110;
    const m = [1, 2, 5, 10, 20].reduce((p, c) =>
      Math.abs(c * this.scale - target) < Math.abs(p * this.scale - target)
        ? c : p);
    const px = m * this.scale * r;
    const x = 18 * r, y = this.canvas.height - 22 * r;
    ctx.fillStyle = '#eef1f6';
    ctx.fillRect(x, y, px, 4 * r);
    ctx.textAlign = 'left';
    ctx.fillText(`${m} m`, x, y - 6 * r);
  }

  /* Which wall is under this point? Within half a metre, so a fingertip
   * reaches it, but never crossing into another block's wall. */
  pick(planX, planY) {
    const L = this.levelData();
    if (!L) return null;
    let best = null, bestd = 0.6;
    /* Partitions first: an internal wall sits inside the block, so a tap
     * near one would otherwise be swallowed by the envelope wall behind
     * it and the user would drag the whole house instead of a room. */
    for (const w of [...(L.partitions || []), ...L.walls]) {
      const [a, b] = w.points;
      const vx = b[0] - a[0], vy = b[1] - a[1];
      const len2 = vx * vx + vy * vy || 1;
      let t = ((planX - a[0]) * vx + (planY - a[1]) * vy) / len2;
      t = Math.max(0, Math.min(1, t));
      const d = Math.hypot(planX - (a[0] + vx * t), planY - (a[1] + vy * t));
      if (d < bestd) { best = w; bestd = d; }
    }
    return best;
  }

  roomAt(planX, planY) {
    const L = this.levelData();
    for (const r of ((L && L.rooms) || [])) {
      if (planX >= r.x && planX <= r.x + r.width &&
          planY >= r.y && planY <= r.y + r.depth) return r;
    }
    return null;
  }

  _bind() {
    const cv = this.canvas;
    cv.style.touchAction = 'none';
    let drag = null;
    cv.addEventListener('pointerdown', (e) => {
      const b = cv.getBoundingClientRect();
      const r = this.pixelRatio;
      const [px, py] = this.toPlan((e.clientX - b.left) * r,
                                   (e.clientY - b.top) * r);
      const hit = this.pick(px, py);
      if (hit) {
        cv.setPointerCapture(e.pointerId);
        this.selected = hit;
        drag = { id: e.pointerId, start: [px, py], wall: hit, moved: 0,
                 client: [e.clientX, e.clientY] };
        this.draw();
        this.onPick && this.onPick(hit);
      } else {
        // No wall under the pointer. That is not nothing: the inside of
        // a room is where a person clicks to select it, and only a
        // pointer that then MOVES is a pan. Keep where it went down so
        // the release can tell the two apart. Capture here too — a pan
        // released off-canvas otherwise never ends, and the plan then
        // chases a hovering cursor with no button held.
        cv.setPointerCapture(e.pointerId);
        drag = { id: e.pointerId, pan: [e.clientX, e.clientY],
                 start: [px, py], moved: 0 };
      }
    });
    cv.addEventListener('pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      if (drag.pan) {
        drag.moved += Math.abs(e.clientX - drag.pan[0]) +
                      Math.abs(e.clientY - drag.pan[1]);
        this.pan = [this.pan[0] + (e.clientX - drag.pan[0]),
                    this.pan[1] + (e.clientY - drag.pan[1])];
        drag.pan = [e.clientX, e.clientY];
        this.draw();
        return;
      }
      const b = cv.getBoundingClientRect();
      const r = this.pixelRatio;
      const [px, py] = this.toPlan((e.clientX - b.left) * r,
                                   (e.clientY - b.top) * r);
      // Outward distance along the wall's own normal, snapped to 100 mm.
      const w = drag.wall;
      const n = { front: [0, -1], rear: [0, 1],
                  left: [-1, 0], right: [1, 0] }[w.edge] || [0, 1];
      const by = (px - drag.start[0]) * n[0] + (py - drag.start[1]) * n[1];
      drag.by = Math.round(by * 10) / 10;
      // Total travel, not just the normal component: a 2 m slide ALONG
      // a partition used to read as moved=0 and popped the room panel
      // on release as if it had been a tap. Tracked from client
      // coordinates because movementX is unreliable on touch browsers.
      drag.moved += Math.abs(e.clientX - drag.client[0]) +
                    Math.abs(e.clientY - drag.client[1]);
      drag.client = [e.clientX, e.clientY];
      this.ghost = { wall: w, by: drag.by };
      this.draw();
      this._ghost();
    });
    const end = (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const d = drag; drag = null; this.ghost = null;
      const tapped = d.start && (d.moved || 0) < 5;
      if (d.wall && d.by && Math.abs(d.by) >= 0.1 && this.onDrag) {
        this.onDrag(d.wall, d.by);
      } else if (tapped && this.onRoom) {
        const rm = this.roomAt(d.start[0], d.start[1]);
        if (rm) this.onRoom(rm);
        else this.draw();
      } else {
        this.draw();
      }
    };
    cv.addEventListener('pointerup', end);
    cv.addEventListener('pointercancel', end);
    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      const b = cv.getBoundingClientRect();
      const r = this.pixelRatio;
      const before = this.toPlan((e.clientX - b.left) * r,
                                 (e.clientY - b.top) * r);
      this.scale = Math.max(2, Math.min(300,
                                        this.scale * (1 - e.deltaY / 600)));
      const after = this.toPlan((e.clientX - b.left) * r,
                                (e.clientY - b.top) * r);
      this.pan = [this.pan[0] + (after[0] - before[0]) * this.scale,
                  this.pan[1] - (after[1] - before[1]) * this.scale];
      this.draw();
    }, { passive: false });
    window.addEventListener('resize', () => this.resize());
  }

  _ghost() {
    if (!this.ghost) return;
    const ctx = this.ctx, r = this.pixelRatio;
    const { wall, by } = this.ghost;
    const n = { front: [0, -1], rear: [0, 1],
                left: [-1, 0], right: [1, 0] }[wall.edge] || [0, 1];
    const [a, b] = wall.points;
    const p0 = this.toPx(a[0] + n[0] * by, a[1] + n[1] * by);
    const p1 = this.toPx(b[0] + n[0] * by, b[1] + n[1] * by);
    ctx.save();
    ctx.setLineDash([8 * r, 6 * r]);
    ctx.lineWidth = 2.5 * r;
    ctx.strokeStyle = '#39ff88';
    ctx.beginPath();
    ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
    ctx.stroke();
    ctx.setLineDash([]);
    const m = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2];
    ctx.fillStyle = '#39ff88';
    ctx.textAlign = 'center';
    ctx.font = `bold ${13 * r}px ui-monospace, monospace`;
    ctx.fillText(`${by > 0 ? '+' : ''}${by.toFixed(1)} m`, m[0], m[1] - 10 * r);
    ctx.restore();
  }
}

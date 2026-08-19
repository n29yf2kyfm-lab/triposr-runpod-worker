/* Stage 3: the 3D world. Our own WebGL, ~400 lines, no dependency.
 *
 * WHY NOT THREE.JS. It is a good library and it is 600 KB that must be
 * bundled and served, and this product's promise is that it works with
 * nothing fetched at view time. What is actually needed here — extruded
 * prisms, roof planes, a terrain grid, an orbit camera and one
 * directional light — is a few hundred lines of WebGL. The trade only
 * favours a library when you need what a library has: skinning,
 * post-processing, glTF. We need none of it yet, and when we do the
 * renderer is behind an interface.
 *
 * WHAT IS HONEST IN 3D. Classification survives into the third
 * dimension: verified geometry is gold, derived is blue, estimated is
 * violet, user edits are green. A block whose storey count was guessed
 * does not get to look like a surveyed one just because it is now a
 * solid with a shadow on it.
 */
'use strict';

const VERT = `
attribute vec3 aPos;
attribute vec3 aNormal;
attribute vec3 aColor;
attribute vec3 aUV;          /* s, t, and 1.0 where the vertex is mapped */
uniform mat4 uMVP;
uniform mat4 uModel;
varying vec3 vNormal;
varying vec3 vColor;
varying vec3 vWorld;
varying vec3 vUV;
void main() {
  vNormal = mat3(uModel) * aNormal;
  vColor = aColor;
  vUV = aUV;
  vWorld = (uModel * vec4(aPos, 1.0)).xyz;
  gl_Position = uMVP * vec4(aPos, 1.0);
}`;

const FRAG = `
precision mediump float;
varying vec3 vNormal;
varying vec3 vColor;
varying vec3 vWorld;
varying vec3 vUV;
uniform vec3 uSun;
uniform float uOpacity;
uniform sampler2D uGround;
void main() {
  vec3 n = normalize(vNormal);
  float d = max(dot(n, normalize(uSun)), 0.0);
  /* Sky fill from above, warm sun, and a touch of ambient so a north
     face is shaded rather than black — a black wall reads as a hole. */
  float sky = 0.5 + 0.5 * n.y;
  vec3 lit = vColor * (0.30 + 0.30 * sky + 0.62 * d);
  if (vUV.z > 0.5) {
    /* AERIAL IMAGERY IS ALREADY LIT. It was photographed in real sun,
       so running it through the same lambert as a wall lights it
       twice and it comes out looking like painted card. Show it near
       enough as captured, knocked back a shade so the model reads in
       front of it. */
    lit = texture2D(uGround, vUV.xy).rgb * 0.94;
  }
  gl_FragColor = vec4(lit, uOpacity);
}`;

function compile(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new Error('shader: ' + gl.getShaderInfoLog(s));
  }
  return s;
}

/* --- small matrix library. Column-major, like GL wants. ------------- */
export const M4 = {
  identity: () => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]),
  perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([
      f / aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
  },
  ortho(l, r, b, t, n, f) {
    return new Float32Array([
      2/(r-l),0,0,0, 0,2/(t-b),0,0, 0,0,-2/(f-n),0,
      -(r+l)/(r-l), -(t+b)/(t-b), -(f+n)/(f-n), 1]);
  },
  lookAt(eye, at, up) {
    const z = norm(sub(eye, at)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([
      x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
      -dot(x,eye), -dot(y,eye), -dot(z,eye), 1]);
  },
  mul(a, b) {
    const o = new Float32Array(16);
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
      o[i * 4 + j] = a[j] * b[i * 4] + a[4 + j] * b[i * 4 + 1] +
                     a[8 + j] * b[i * 4 + 2] + a[12 + j] * b[i * 4 + 3];
    }
    return o;
  },
};
const sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
                         a[0]*b[1]-a[1]*b[0]];
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const norm = (a) => { const l = Math.hypot(...a) || 1;
                      return [a[0]/l, a[1]/l, a[2]/l]; };

export const CLASS_RGB = {
  verified:  [1.00, 0.84, 0.18],
  derived:   [0.31, 0.76, 0.97],
  estimated: [0.69, 0.52, 0.96],
  user:      [0.22, 1.00, 0.53],
};

/* --- mesh building --------------------------------------------------
 * All geometry is built on the CPU into one buffer per frame-set. The
 * models here are tens of triangles, not millions; a rebuild costs
 * microseconds and removes every class of stale-buffer bug. */
class MeshBuilder {
  constructor() {
    this.pos = []; this.nrm = []; this.col = []; this.uv = [];
  }

  /* `uvs` is optional: three [s, t] pairs when this triangle is to be
   * drawn from the ground image instead of its own colour. The third
   * component is the flag the shader branches on, so an untextured
   * mesh needs no second draw call and no second program. */
  tri(a, b, c, colour, uvs) {
    const n = norm(cross(sub(b, a), sub(c, a)));
    [a, b, c].forEach((p, i) => {
      this.pos.push(p[0], p[1], p[2]);
      this.nrm.push(n[0], n[1], n[2]);
      this.col.push(colour[0], colour[1], colour[2]);
      if (uvs) this.uv.push(uvs[i][0], uvs[i][1], 1);
      else this.uv.push(0, 0, 0);
    });
  }

  quad(a, b, c, d, colour, uvs) {
    this.tri(a, b, c, colour, uvs && [uvs[0], uvs[1], uvs[2]]);
    this.tri(a, c, d, colour, uvs && [uvs[0], uvs[2], uvs[3]]);
  }

  /* A block: walls from base to eaves, plus its roof. Plan coordinates
   * are (x, y) metres in the building frame; GL is y-up, so plan y maps
   * to -z, exactly as the OBJ exporter in building/ does. */
  block(solid, colour) {
    const r = solid.ring.slice(0, -1);
    const b = solid.base_m, e = solid.eaves_m;
    const P = (x, y, z) => [x, z, -y];
    for (let i = 0; i < r.length; i++) {
      const [x0, y0] = r[i], [x1, y1] = r[(i + 1) % r.length];
      this.quad(P(x0, y0, b), P(x1, y1, b), P(x1, y1, e), P(x0, y0, e), colour);
    }
    const roof = solid.roof || {};
    const kind = roof.kind || 'flat';
    const xs = r.map((p) => p[0]), ys = r.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const rc = colour.map((v) => v * 0.82);

    if (kind === 'flat' || !roof.pitch_deg) {
      this.quad(P(x0, y0, e), P(x1, y0, e), P(x1, y1, e), P(x0, y1, e), rc);
      return;
    }
    const alongX = (roof.ridge_along || 'y') === 'x';
    const span = alongX ? (y1 - y0) : (x1 - x0);
    const t = Math.tan(roof.pitch_deg * Math.PI / 180);

    if (kind === 'monopitch') {
      const rise = span * t, top = e + rise;
      const high = roof.high_side === 'max';
      if (alongX) {
        const ry = high ? y1 : y0, ly = high ? y0 : y1;
        this.quad(P(x0, ly, e), P(x1, ly, e), P(x1, ry, top), P(x0, ry, top), rc);
        this.tri(P(x0, ly, e), P(x0, ry, top), P(x0, ry, e), rc);
        this.tri(P(x1, ly, e), P(x1, ry, e), P(x1, ry, top), rc);
      } else {
        const rx = high ? x1 : x0, lx = high ? x0 : x1;
        this.quad(P(lx, y0, e), P(lx, y1, e), P(rx, y1, top), P(rx, y0, top), rc);
        this.tri(P(lx, y0, e), P(rx, y0, top), P(rx, y0, e), rc);
        this.tri(P(lx, y1, e), P(rx, y1, e), P(rx, y1, top), rc);
      }
      return;
    }
    // gabled / hipped
    const rise = (span / 2) * t, top = e + rise;
    if (alongX) {
      const my = (y0 + y1) / 2;
      const [rx0, rx1] = kind === 'hipped'
        ? [x0 + (y1 - y0) / 2, x1 - (y1 - y0) / 2] : [x0, x1];
      this.quad(P(x0, y0, e), P(x1, y0, e), P(rx1, my, top), P(rx0, my, top), rc);
      this.quad(P(x1, y1, e), P(x0, y1, e), P(rx0, my, top), P(rx1, my, top), rc);
      this.tri(P(x0, y1, e), P(x0, y0, e), P(rx0, my, top), rc);
      this.tri(P(x1, y0, e), P(x1, y1, e), P(rx1, my, top), rc);
    } else {
      const mx = (x0 + x1) / 2;
      const [ry0, ry1] = kind === 'hipped'
        ? [y0 + (x1 - x0) / 2, y1 - (x1 - x0) / 2] : [y0, y1];
      this.quad(P(x0, y0, e), P(x0, y1, e), P(mx, ry1, top), P(mx, ry0, top), rc);
      this.quad(P(x1, y1, e), P(x1, y0, e), P(mx, ry0, top), P(mx, ry1, top), rc);
      this.tri(P(x0, y0, e), P(x1, y0, e), P(mx, ry0, top), rc);
      this.tri(P(x1, y1, e), P(x0, y1, e), P(mx, ry1, top), rc);
    }
  }

  ground(x0, y0, x1, y1, colour) {
    const P = (x, y, z) => [x, z, -y];
    this.quad(P(x0, y0, 0), P(x1, y0, 0), P(x1, y1, 0), P(x0, y1, 0), colour);
  }

  /* The imagery, draped where it actually belongs. The corners arrive
   * from the server already rotated into the building frame, so a house
   * that sits at 20 degrees to north gets imagery at 20 degrees too
   * rather than an axis-aligned smear under a rotated model. */
  groundImage(corners) {
    const P = (x, y, z) => [x, z, -y];
    const [sw, se, ne, nw] = corners;
    const z = 0.015;            // clear of the plane it lies on
    this.quad(P(sw[0], sw[1], z), P(se[0], se[1], z),
              P(ne[0], ne[1], z), P(nw[0], nw[1], z),
              [1, 1, 1], [[0, 1], [1, 1], [1, 0], [0, 0]]);
  }

  count() { return this.pos.length / 3; }
}

/* --- the viewer ----------------------------------------------------- */
export class Viewer3D {
  constructor(canvas) {
    this.canvas = canvas;
    const gl = canvas.getContext('webgl', { antialias: true, alpha: false });
    if (!gl) throw new Error('WebGL is not available in this browser');
    this.gl = gl;
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error('link: ' + gl.getProgramInfoLog(p));
    }
    this.prog = p;
    this.loc = {
      aPos: gl.getAttribLocation(p, 'aPos'),
      aNormal: gl.getAttribLocation(p, 'aNormal'),
      aColor: gl.getAttribLocation(p, 'aColor'),
      aUV: gl.getAttribLocation(p, 'aUV'),
      uMVP: gl.getUniformLocation(p, 'uMVP'),
      uModel: gl.getUniformLocation(p, 'uModel'),
      uSun: gl.getUniformLocation(p, 'uSun'),
      uOpacity: gl.getUniformLocation(p, 'uOpacity'),
      uGround: gl.getUniformLocation(p, 'uGround'),
    };
    this.buf = { pos: gl.createBuffer(), nrm: gl.createBuffer(),
                 col: gl.createBuffer(), uv: gl.createBuffer() };
    this.groundTex = null;      // GL texture, once imagery has arrived
    this.groundQuad = null;     // its four corners, in building metres
    this.groundInfo = null;     // source, licence, attribution
    this.vertices = 0;
    this.yaw = 0.7; this.pitch = 0.55; this.dist = 40;
    this.target = [0, 0, 0];
    this.projection = 'perspective';
    this.sun = [-0.45, 0.78, 0.44];
    this._bind();
    this.resize();
  }

  get pixelRatio() { return Math.min(2, window.devicePixelRatio || 1); }

  resize() {
    const r = this.pixelRatio;
    this.canvas.width = Math.floor((this.canvas.clientWidth || 800) * r);
    this.canvas.height = Math.floor((this.canvas.clientHeight || 600) * r);
    this.render();
  }

  /* Build from a massing payload: solids in building-frame metres. */
  setMassing(massing, opts = {}) {
    const mb = new MeshBuilder();
    const solids = massing.solids || [];
    let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
    for (const s of solids) {
      for (const [x, y] of s.ring) {
        minx = Math.min(minx, x); maxx = Math.max(maxx, x);
        miny = Math.min(miny, y); maxy = Math.max(maxy, y);
      }
    }
    if (!solids.length) { minx = miny = -5; maxx = maxy = 5; }
    this._massing = massing;
    const pad = Math.max(8, (maxx - minx) * 0.8);
    /* The plain plane is drawn EITHER WAY, and the imagery sits just
     * above it. The imagery covers a fixed box round the house, so on
     * its own it left a void at the edge of the world that read as a
     * hole in the ground. Underlay first, photograph on top. */
    // Big enough that the camera never sees its edge at any orbit;
    // it costs two triangles.
    const gpad = Math.max(pad, 400);
    mb.ground(minx - gpad, miny - gpad, maxx + gpad, maxy + gpad,
              [0.18, 0.21, 0.17]);
    if (this.groundTex && this.groundQuad) mb.groundImage(this.groundQuad);
    if (massing.traced_ring && opts.showTraced !== false) {
      // The surveyed outline, laid on the ground as a thin plate so the
      // fitted rectangle can be compared against what was actually there.
      const r = massing.traced_ring;
      const P = (x, y, z) => [x, z, -y];
      for (let i = 1; i < r.length - 1; i++) {
        mb.tri(P(r[0][0], r[0][1], 0.02), P(r[i][0], r[i][1], 0.02),
               P(r[i + 1][0], r[i + 1][1], 0.02), [0.42, 0.40, 0.30]);
      }
    }
    for (const s of solids) {
      mb.block(s, CLASS_RGB[s.classification] || CLASS_RGB.estimated);
    }
    this._upload(mb);
    this.target = [(minx + maxx) / 2, 0, -(miny + maxy) / 2];
    this.extent = Math.max(maxx - minx, maxy - miny, 6);
    if (opts.frame !== false) this.dist = this.extent * 2.1;
    this.render();
    return { vertices: mb.count(), solids: solids.length };
  }

  _upload(mb) {
    const gl = this.gl;
    const put = (b, arr) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(arr), gl.STATIC_DRAW);
    };
    put(this.buf.pos, mb.pos);
    put(this.buf.nrm, mb.nrm);
    put(this.buf.col, mb.col);
    put(this.buf.uv, mb.uv);
    this.vertices = mb.count();
  }

  /* Drape real imagery under the model.
   *
   * WHY THIS MATTERS MORE THAN IT LOOKS. A correct model on a blank
   * plane still reads as CGI, because a building with no context looks
   * like a render of nothing — which is exactly the complaint that a
   * measured model "does not look like the house". The imagery is not
   * decoration: it is the only thing on screen that tells you the
   * model is standing in the right place, at the right angle, at the
   * right size, against its actual neighbours.
   *
   * It stays a TEXTURE and never becomes geometry. Nothing measured is
   * taken from it, so no licence that permits display but forbids
   * extraction is strained by it — and the attribution travels with it
   * in groundInfo for whatever is showing the canvas to print.
   */
  setGround(imageUrl, cornersM, info) {
    return new Promise((resolve, reject) => {
      const gl = this.gl;
      const im = new Image();
      im.onload = () => {
        const t = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB,
                      gl.UNSIGNED_BYTE, im);
        /* WebGL1 will not mipmap a non-power-of-two image, and every
         * stitched crop is one. Clamp and stay linear, or the ground
         * comes back black with no error anywhere. */
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        if (this.groundTex) gl.deleteTexture(this.groundTex);
        this.groundTex = t;
        this.groundQuad = cornersM;
        this.groundInfo = info || null;
        if (this._massing) this.setMassing(this._massing, { frame: false });
        else this.render();
        resolve(true);
      };
      im.onerror = () => reject(new Error('ground imagery would not load'));
      im.src = imageUrl;
    });
  }

  clearGround() {
    if (this.groundTex) this.gl.deleteTexture(this.groundTex);
    this.groundTex = null;
    this.groundQuad = null;
    this.groundInfo = null;
    if (this._massing) this.setMassing(this._massing, { frame: false });
  }

  setView(name) {
    const v = {
      top:   [0, 1.5533],       // yaw, pitch (near vertical)
      front: [0, 0.05],
      rear:  [Math.PI, 0.05],
      left:  [-Math.PI / 2, 0.05],
      right: [Math.PI / 2, 0.05],
      iso:   [0.7, 0.55],
    }[name];
    if (v) { this.yaw = v[0]; this.pitch = v[1]; this.render(); }
    return this;
  }

  setProjection(kind) {
    this.projection = kind === 'ortho' ? 'ortho' : 'perspective';
    this.render();
  }

  camera() {
    const d = this.dist;
    return [
      this.target[0] + Math.sin(this.yaw) * Math.cos(this.pitch) * d,
      this.target[1] + Math.sin(this.pitch) * d,
      this.target[2] + Math.cos(this.yaw) * Math.cos(this.pitch) * d,
    ];
  }

  render() {
    const gl = this.gl;
    const w = this.canvas.width, h = this.canvas.height;
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.055, 0.067, 0.086, 1);
    gl.enable(gl.DEPTH_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.vertices) return;
    const eye = this.camera();
    const view = M4.lookAt(eye, this.target, [0, 1, 0]);
    const aspect = w / Math.max(1, h);
    const proj = this.projection === 'ortho'
      ? M4.ortho(-this.dist * 0.5 * aspect, this.dist * 0.5 * aspect,
                 -this.dist * 0.5, this.dist * 0.5, -2000, 4000)
      : M4.perspective(45 * Math.PI / 180, aspect, 0.1, 6000);
    const model = M4.identity();
    gl.useProgram(this.prog);
    gl.uniformMatrix4fv(this.loc.uMVP, false, M4.mul(proj, view));
    gl.uniformMatrix4fv(this.loc.uModel, false, model);
    gl.uniform3fv(this.loc.uSun, new Float32Array(this.sun));
    gl.uniform1f(this.loc.uOpacity, 1.0);
    const attach = (buf, loc, size) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    };
    attach(this.buf.pos, this.loc.aPos, 3);
    attach(this.buf.nrm, this.loc.aNormal, 3);
    attach(this.buf.col, this.loc.aColor, 3);
    attach(this.buf.uv, this.loc.aUV, 3);
    if (this.groundTex) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.groundTex);
      gl.uniform1i(this.loc.uGround, 0);
    }
    gl.drawArrays(gl.TRIANGLES, 0, this.vertices);
  }

  /* Sun direction for a real date, time and latitude — Stage 3 groundwork
   * for the shadow study. NOAA's low-precision algorithm, good to about
   * a degree, which is far inside what a massing study can justify. */
  setSun(lat, lonDeg, date) {
    const rad = Math.PI / 180;
    const start = Date.UTC(date.getUTCFullYear(), 0, 0);
    const day = (date.getTime() - start) / 86400000;
    const g = (357.529 + 0.98560028 * day) * rad;
    const q = (280.459 + 0.98564736 * day) * rad;
    const L = q + (1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
    const e = (23.439 - 0.00000036 * day) * rad;
    const dec = Math.asin(Math.sin(e) * Math.sin(L));
    const hours = date.getUTCHours() + date.getUTCMinutes() / 60;
    const ha = ((hours - 12) * 15 + lonDeg) * rad;
    const la = lat * rad;
    const alt = Math.asin(Math.sin(la) * Math.sin(dec) +
                          Math.cos(la) * Math.cos(dec) * Math.cos(ha));
    const az = Math.atan2(-Math.sin(ha),
                          Math.tan(dec) * Math.cos(la) - Math.sin(la) * Math.cos(ha));
    // Below the horizon is night: keep a dim fill rather than a black model.
    const a = Math.max(alt, 0.08);
    this.sun = [Math.sin(az) * Math.cos(a), Math.sin(a), -Math.cos(az) * Math.cos(a)];
    this.render();
    return { altitude_deg: alt / rad, azimuth_deg: ((az / rad) + 360) % 360,
             above_horizon: alt > 0 };
  }

  _bind() {
    const cv = this.canvas;
    cv.style.touchAction = 'none';
    const pts = new Map();
    let drag = null, pinch = null;
    cv.addEventListener('pointerdown', (e) => {
      cv.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      drag = pts.size === 1 ? { id: e.pointerId, x: e.clientX, y: e.clientY }
                            : null;
      pinch = null;
    });
    cv.addEventListener('pointermove', (e) => {
      if (pts.has(e.pointerId)) pts.set(e.pointerId,
                                        { x: e.clientX, y: e.clientY });
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch) this.dist = Math.max(3, Math.min(this.extent * 12,
                                                    this.dist * pinch / d));
        pinch = d; this.render(); return;
      }
      if (!drag || e.pointerId !== drag.id) return;
      this.yaw -= (e.clientX - drag.x) * 0.008;
      this.pitch = Math.max(0.02, Math.min(1.553,
                            this.pitch + (e.clientY - drag.y) * 0.006));
      drag.x = e.clientX; drag.y = e.clientY;
      this.render();
    });
    const end = (e) => { pts.delete(e.pointerId);
                         if (pts.size < 2) pinch = null;
                         if (drag && e.pointerId === drag.id) drag = null; };
    cv.addEventListener('pointerup', end);
    cv.addEventListener('pointercancel', end);
    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.dist = Math.max(3, Math.min(this.extent * 12,
                                       this.dist * (1 + e.deltaY / 600)));
      this.render();
    }, { passive: false });
    window.addEventListener('resize', () => this.resize());
  }
}

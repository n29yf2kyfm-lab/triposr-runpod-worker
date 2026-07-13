/* car-viewer.js — free/open-source (MIT) Three.js car viewer for ExpertCarCheck.
 *
 * Features: OrbitControls, damped rotation, clamped zoom, environment reflections,
 * correct colour management (sRGB + ACES), contact shadows, paint-colour switching,
 * door/bonnet/boot open toggles (when those nodes exist), loading progress,
 * mobile-friendly controls, WebGL fallback. Loads Draco, Meshopt and KTX2 when
 * the GLB uses them.
 *
 * Usage (ES module):
 *   import { CarViewer } from './car-viewer.js';
 *   const v = new CarViewer(document.getElementById('stage'), {
 *     src: '/build/golf.draco.glb',
 *     onProgress: p => {}, onReady: () => {}, onError: e => {}
 *   });
 *   v.setPaint('#3a4049');           // recolour the body-paint material only
 *   v.toggle('door');                // open/close doors if present
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const PAINT_MATCH = /(car[\s_-]?paint|body[\s_-]?paint|\bpaint\b|\bbody\b|lack|coat|exterior)/i;

export class CarViewer {
  constructor(container, opts = {}) {
    this.opts = opts; this.container = container;
    this.parts = { door: [], bonnet: [], boot: [] };
    this._open = {};
    if (!this._webglOK()) { this._fallback(); return; }
    this._initRenderer(); this._initScene(); this._load(opts.src);
    window.addEventListener('resize', () => this._resize());
    this._animate();
  }
  _webglOK() { try { const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl'))); } catch { return false; } }
  _fallback() {
    this.container.innerHTML =
      '<div style="display:grid;place-items:center;height:100%;color:#93a1b2;font:14px system-ui;text-align:center;padding:24px">' +
      '3D view needs WebGL. Showing the standard photo instead.</div>';
    if (this.opts.onError) this.opts.onError(new Error('no-webgl'));
  }
  _initRenderer() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.shadowMap.enabled = true;
    this.container.appendChild(this.renderer.domElement);
  }
  _initScene() {
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, this._aspect(), 0.1, 100);
    this.camera.position.set(4.2, 1.8, 5.4);            // 3/4 front default
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08,
      minDistance: 3, maxDistance: 9, maxPolarAngle: Math.PI / 1.9, enablePan: false });
    // soft contact shadow (a dark radial plane; cheap on mobile)
    const g = new THREE.CircleGeometry(3.2, 48);
    const tex = this._shadowTexture();
    const m = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.55, depthWrite: false });
    this.shadow = new THREE.Mesh(g, m); this.shadow.rotation.x = -Math.PI / 2; this.shadow.position.y = 0.001;
    this.scene.add(this.shadow);
  }
  _shadowTexture() {
    const s = 256, c = document.createElement('canvas'); c.width = c.height = s;
    const x = c.getContext('2d'), grd = x.createRadialGradient(s/2, s/2, 8, s/2, s/2, s/2);
    grd.addColorStop(0, 'rgba(0,0,0,.85)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
    x.fillStyle = grd; x.fillRect(0, 0, s, s);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  _load(src) {
    const draco = new DRACOLoader().setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.6/');
    const ktx2 = new KTX2Loader().setTranscoderPath('https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/libs/basis/').detectSupport(this.renderer);
    const loader = new GLTFLoader().setDRACOLoader(draco).setKTX2Loader(ktx2).setMeshoptDecoder(MeshoptDecoder);
    loader.load(src, (gltf) => {
      this.model = gltf.scene; this.clips = gltf.animations || [];
      this.mixer = this.clips.length ? new THREE.AnimationMixer(this.model) : null;
      this._catalogueParts(); this._frame(); this.scene.add(this.model);
      if (this.opts.onReady) this.opts.onReady(this);
    }, (e) => { if (this.opts.onProgress && e.total) this.opts.onProgress(e.loaded / e.total); },
       (err) => { if (this.opts.onError) this.opts.onError(err); });
  }
  _catalogueParts() {
    this.paintMats = [];
    this.model.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        const nm = (o.material && o.material.name || '') + ' ' + o.name;
        if (PAINT_MATCH.test(nm) && o.material && o.material.color) this.paintMats.push(o.material);
      }
      const n = o.name.toLowerCase();
      if (/door|puerta/.test(n)) this.parts.door.push(o);
      else if (/bonnet|hood|capot/.test(n)) this.parts.bonnet.push(o);
      else if (/boot|trunk|tailgate|hatch/.test(n)) this.parts.boot.push(o);
    });
  }
  _frame() {
    const box = new THREE.Box3().setFromObject(this.model);
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    this.model.position.sub(c); this.model.position.y += s.y / 2;       // sit on the ground
    const r = Math.max(s.x, s.y, s.z);
    this.controls.target.set(0, s.y * 0.45, 0);
    this.camera.position.set(r * 0.9, r * 0.42, r * 1.15); this.controls.update();
  }
  /** Recolour ONLY the detected body-paint material(s). */
  setPaint(hex) { const c = new THREE.Color(hex);
    this.paintMats.forEach((m) => { m.color.copy(c); if ('metalness' in m) m.metalness = 0.85; if ('roughness' in m) m.roughness = 0.28; }); }
  /** Open/close a panel group if the model provides a matching animation clip. */
  toggle(part) {
    if (!this.mixer) return false;
    const clip = this.clips.find((c) => new RegExp(part, 'i').test(c.name));
    if (!clip) return false;
    const a = this.mixer.clipAction(clip); a.clampWhenFinished = true; a.loop = THREE.LoopOnce;
    this._open[part] = !this._open[part];
    a.timeScale = this._open[part] ? 1 : -1;
    if (a.time === 0 && !this._open[part]) a.time = clip.duration;
    a.paused = false; a.play(); return true;
  }
  _aspect() { return this.container.clientWidth / Math.max(1, this.container.clientHeight); }
  _resize() { if (!this.renderer) return; this.camera.aspect = this._aspect(); this.camera.updateProjectionMatrix();
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight); }
  _animate() { this._raf = requestAnimationFrame(() => this._animate());
    if (this.mixer) this.mixer.update(1 / 60); this.controls.update(); this.renderer.render(this.scene, this.camera); }
  dispose() { cancelAnimationFrame(this._raf); this.renderer && this.renderer.dispose(); }
}

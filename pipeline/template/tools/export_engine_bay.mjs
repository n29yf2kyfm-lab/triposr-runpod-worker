import puppeteer from 'puppeteer-core';
import fs from 'fs';
const [,, out] = process.argv;
const IDS = ['engine-bay-structure','battery-assembly','battery-negative-earth-lead','radiator-condenser-cooling-pack','radiator-upper-hose','radiator-lower-hose',
 'radiator-upper-engine-hose-clamp','radiator-upper-radiator-hose-clamp','radiator-lower-radiator-hose-clamp','radiator-lower-engine-hose-clamp','coolant-expansion-reservoir','coolant-degas-hose',
 'gearbox-case','bellhousing','mechatronic-cover','transmission-oil-filter','transmission-oil-cooler','integrated-front-differential','cv-output-left','cv-output-right',
 'blk','sump','head','cam_cover','timing_cover','coolant_pump',
 'dgea_coils','dgea_filler','dgea_intake','dgea_airbox','dgea_chargepipe','dgea_turbo','dgea_mount','dgea_pulley','dgea_thermo','dgea_oilfilter','dgea_epump','dgea_loom',
 'exhaust_front','exhaust_rear','fuel_tank','susp_rear','subframe_f','arb_f',
 'knuckle_fl','strut_fl','droplink_fl','tre_fl','bj_fl','arm_fl','ds_fl','knuckle_fr','strut_fr','droplink_fr','tre_fr','bj_fr','arm_fr','ds_fr'];
const b = await puppeteer.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader'] });
const p = await b.newPage(); await p.setViewport({ width: 800, height: 600 });
p.on('pageerror', e => console.log('pageerror: '+e.message));
await p.goto('http://localhost:8765/index.html?debug', { waitUntil: 'domcontentloaded' });
await p.waitForFunction(() => window.__ws, { timeout: 300000 });
await p.addScriptTag({ type: 'module', content: "import { GLTFExporter } from './lib/addons/exporters/GLTFExporter.js'; window.__GLTFExporter = GLTFExporter;" });
await p.waitForFunction(() => window.__GLTFExporter, { timeout: 60000 });
const b64 = await p.evaluate(async (IDS) => {
  const { byId, THREE, scene } = window.__ws;
  const GLTFExporter = window.__GLTFExporter;
  const memo = new Map();
  // procedural DataTextures cannot be drawn by the exporter: turn 8-bit RGBA ones into canvases, drop the rest
  const fixTex = t => {
    if (!t || !t.isDataTexture) return t;
    if (memo.has(t)) return memo.get(t);
    let out = null; const im = t.image;
    if (im && im.data && im.data.length === im.width * im.height * 4 && im.data instanceof Uint8Array) {
      const c = document.createElement('canvas'); c.width = im.width; c.height = im.height;
      c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(im.data), im.width, im.height), 0, 0);
      out = new THREE.CanvasTexture(c); out.wrapS = t.wrapS; out.wrapT = t.wrapT; out.repeat.copy(t.repeat); out.colorSpace = t.colorSpace;
    }
    memo.set(t, out); return out;
  };
  const mmemo = new Map();
  const fixMat = mat => {
    if (mmemo.has(mat)) return mmemo.get(mat);
    const c = mat.clone(); mmemo.set(mat, c);
    for (const k of ['map','normalMap','roughnessMap','metalnessMap','aoMap','emissiveMap','bumpMap','alphaMap','clearcoatNormalMap']) if (c[k]) c[k] = fixTex(c[k]);
    if (c.bumpMap) c.bumpMap = null;
    return c;
  };
  const root = new THREE.Group(); root.name = 'engine_bay';
  scene.updateMatrixWorld(true);
  const carRoot = byId.body.obj.parent; const inv = carRoot.matrixWorld.clone().invert();
  const missing = [];
  for (const id of IDS) {
    const q = byId[id]; if (!q) { missing.push(id); continue; }
    const g = new THREE.Group(); g.name = 'bay:' + id; root.add(g);
    q.obj.traverse(o => {
      if (!o.isMesh || !o.visible) return;
      let vis = true; for (let a = o; a; a = a.parent) if (a.visible === false) vis = false;
      if (!vis) return;
      const geo = o.geometry.clone(); geo.applyMatrix4(inv.clone().multiply(o.matrixWorld));
      for (const k of Object.keys(geo.attributes)) if (!['position','normal','uv','color'].includes(k)) geo.deleteAttribute(k);
      const m = new THREE.Mesh(geo, [].concat(o.material).map(fixMat)); if (m.material.length === 1) m.material = m.material[0]; m.name = 'bay:' + id; g.add(m);
    });
  }
  const buf = await new GLTFExporter().parseAsync(root, { binary: true });
  const u8 = new Uint8Array(buf); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return JSON.stringify({ missing, data: btoa(s) });
}, IDS);
const r = JSON.parse(b64); if (r.missing.length) console.log('missing', r.missing);
fs.writeFileSync(out, Buffer.from(r.data, 'base64')); console.log('wrote', out, fs.statSync(out).size);
await b.close();

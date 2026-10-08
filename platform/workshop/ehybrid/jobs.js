import * as THREE from 'three';

/* ═════════════════════════════════════════════════════════════════════
   Tools and fastener specifications for the eHybrid workshop.
   Torque, angle and renew flags marked `man` come from the VW workshop
   manual assembly overviews for the Golf Mk7 (same EA211 1.4 TSI engine
   family, and the hybrid front brake), as extracted into
   platform/trainer/data/golf_mk7_assemblies.json. `class` is the typical
   value Strip Bay uses; `est` means the tool or value is an estimate and the
   real figure has to come from erWin for the exact car.
   Frame: +X is the car's LEFT, +Y up, +Z the nose, metres.
   ═══════════════════════════════════════════════════════════════════ */

export const TOOLS = [
  { k: 'hand', label: 'Hands' }, { k: 'trim', label: 'Trim tool' },
  { k: 't25', label: 'T25 Torx' }, { k: 't30', label: 'T30 Torx' },
  { k: 's10', label: '10 mm socket' }, { k: 's13', label: '13 mm socket' }, { k: 's16', label: '16 mm socket' },
  { k: 's17', label: '17 mm wheel socket' }, { k: 's18', label: '18 mm socket' }, { k: 's21', label: '21 mm socket' }, { k: 'hub', label: 'Hub bolt socket' },
  { k: 's14', label: '14 mm banjo socket' }, { k: 'p12', label: 'M10 12-point' },
  { k: 'plug', label: 'Spark plug socket' }, { k: 'tq', label: 'Torque wrench' }, { k: 'ang', label: 'Angle gauge' },
];
export const toolLabel = k => (TOOLS.find(t => t.k === k) || { label: k }).label;

const MAN = 'VW workshop manual, Golf Mk7 assembly overview';
export const SPEC = {
  fix_bumper_f: { label: 'Bumper cover screws and bolts', tool: 't25', nm: null, src: 'est', note: 'Wheel-arch liner screws, top bolts to the lock carrier and undertray screws. The manual data gives no torque for these: snug them down by hand.' },
  fix_bonnet: { label: 'Bonnet hinge bolts', tool: 's10', nm: null, src: 'est', note: 'Mark round the hinges before undoing them, or you will chase the shut lines on refit. A second person holds the bonnet.', needOpen: 'panel_bonnet' },
  fix_door_fl: { label: 'Front-left door hinge bolts', tool: 's13', nm: null, src: 'est', note: 'Positions measured on this model (Strip Bay). The front-door overview gives no torque in the extracted data. Door open and supported before the last bolt.', needOpen: 'door_fl' },
  fix_door_fr: { label: 'Front-right door hinge bolts', tool: 's13', nm: null, src: 'est', note: 'Mirror of the left door. No torque in the extracted data.', needOpen: 'door_fr' },
  fix_door_rl: { label: 'Rear-left door hinge bolts', tool: 's13', nm: 20, deg: 90, src: 'man', note: 'Rear door hinge bolts: 20 Nm + 90° (' + MAN + ', rear door).', needOpen: 'door_rl' },
  fix_door_rr: { label: 'Rear-right door hinge bolts', tool: 's13', nm: 20, deg: 90, src: 'man', note: 'Rear door hinge bolts: 20 Nm + 90°.', needOpen: 'door_rr' },
  fix_wheel_fl: { label: 'Wheel bolts, front-left', tool: 's17', nm: 120, src: 'class', note: '≈120 Nm is the class value Strip Bay uses; check the handbook for this car. Tighten in a star pattern with the wheel on the ground.' },
  fix_wheel_fr: { label: 'Wheel bolts, front-right', tool: 's17', nm: 120, src: 'class', note: '≈120 Nm class value; tighten in a star.' },
  fix_wheel_rl: { label: 'Wheel bolts, rear-left', tool: 's17', nm: 120, src: 'class', note: '≈120 Nm class value; tighten in a star.' },
  fix_wheel_rr: { label: 'Wheel bolts, rear-right', tool: 's17', nm: 120, src: 'class', note: '≈120 Nm class value; tighten in a star.' },
  spark_plugs: { label: 'Spark plugs', tool: 'plug', nm: 22, src: 'man', note: 'Spark plugs 22 Nm, with the spark plug socket and extension (' + MAN + ', ignition system).' },
  bolts_cam: { label: 'Camshaft housing cover bolts', tool: 's10', nm: 8, src: 'man', note: '8 Nm (' + MAN + ', camshaft housing). Housing-to-head bolts follow the manual sequence figure.' },
  bolts_timing_cover: { label: 'Timing belt cover bolts', tool: 's10', nm: 8, src: 'man', note: '8 Nm (' + MAN + ', toothed belt cover).' },
  bolts_head: { label: 'Cylinder head bolts', tool: 'p12', nm: null, renew: true, src: 'man', note: 'Renew (manual). Loosening and tightening sequence, torque and angle stages are in the manual figure, which is not in the extracted data.' },
  bolts_sump: { label: 'Lower sump bolts', tool: 's10', nm: 5, deg: 90, renew: true, src: 'man', note: 'Lower part of sump: 5 Nm + 90°, renew (' + MAN + ', sump and oil pump).' },
  bolts_main: { label: 'Main bearing bolts', tool: 'p12', nm: null, renew: true, src: 'est', note: 'Stretch bolts: renew. Torque and angle from erWin.' },
  bolts_intake: { label: 'Intercooler cover bolts', tool: 's10', nm: null, src: 'est', note: 'Some intake-manifold bolts are thread-forming (7 Nm in the manual data for that item). The cover figure is in erWin.' },
  bolts_mount: { label: 'Mount bracket bolts', tool: 's16', nm: 60, deg: 90, renew: true, src: 'man', note: 'Assembly mountings: 60 Nm + 90°, renew (' + MAN + ', 1.4 TSI assembly mountings; which bolt is which: check the figure).' },
  bolts_emotor: { label: 'Hybrid module to gearbox bolts', tool: 's16', nm: null, src: 'est', note: 'Value from erWin for the DQ400e.' },
  bolts_inverter: { label: 'Inverter bolts', tool: 's10', nm: null, src: 'est', note: 'Value from erWin.' },
  bolts_battery: { label: 'HV battery mounting bolts', tool: 's16', nm: null, src: 'est', note: 'Value from erWin. Battery lift table under the pack first.' },
  bolts_tank: { label: 'Fuel tank strap bolts', tool: 's13', nm: 20, deg: 90, renew: true, src: 'man', note: 'Securing strap bolts 20 Nm + 90°, renew (' + MAN + ', fuel tank).' },
};

/* the front corners (front-corner.js): figures from the manual's front brake,
   wheel bearing, suspension strut, lower link, steering rack, subframe, speed
   sensor and drive shaft overviews. Socket sizes are estimates. */
const CORNER = {
  bolts_caliper: ['Caliper guide bolts', 's13', 35, 0, true, 'Self-locking hexagon bolts, 35 Nm, renew (front brakes overview). Counterhold the guide pin.'],
  bolts_carrier: ['Brake carrier bolts', 's21', 200, 0, false, 'Ribbed-collar bolts, 200 Nm; clean if reused (front brakes overview).'],
  screw_disc: ['Disc retaining screw', 't30', 4.5, 0, false, 'Torx screw 4.5 Nm (front brakes overview). It only locates the disc: the wheel bolts clamp it.'],
  bolts_splash: ['Splash plate bolts', 't25', 12, 0, false, '12 Nm (wheel bearing and front brakes overviews).'],
  bolt_hub: ['Hub bolt (drive shaft)', 'hub', 200, 180, true, '200 Nm + 180°, renew; clean the thread in the CV joint with a tap first (drive shaft and wheel bearing overviews). Loosen and tighten with the car on its wheels or the hub held.'],
  bolts_bearing: ['Wheel bearing unit bolts', 's16', 70, 90, true, '70 Nm + 90°, renew (wheel bearing assembly overview). Hub bolt out and the shaft pushed back first.'],
  bolt_abs: ['ABS sensor bolt', 't25', 8, 0, false, '8 Nm (speed sensor on front axle overview).'],
  bolt_banjo: ['Brake hose banjo bolt', 's14', 35, 0, false, '35 Nm with new sealing washers (front brakes overview). Bleed the brakes afterwards.'],
  bolt_hosebracket: ['Brake hose bracket bolt', 's10', 8, 0, false, '8 Nm (front brakes overview, bracket).'],
  bolt_strutclamp: ['Strut pinch bolt and nut', 's18', 70, 180, true, '70 Nm + 180°, bolt and nut renewed; the tip of the bolt points in the direction of travel (suspension strut overview).'],
  bolts_topmount: ['Strut top mount bolts', 's13', 15, 90, true, '15 Nm + 90°, renew (suspension strut overview). From the engine bay: the bonnet has to be open.', 'panel_bonnet'],
  nut_bj: ['Swivel joint stud nut', 's18', 60, 0, true, '60 Nm, renew (lower suspension link, swivel joint overview).'],
  nuts_bj: ['Swivel joint to lower link nuts', 's13', 40, 45, true, '40 Nm + 45°, renew, in the unladen position (lower suspension link, swivel joint overview).'],
  nut_tre: ['Track rod end nut', 's16', 20, 90, true, '20 Nm + 90°, renew (steering rack overview).'],
  nuts_droplink: ['Coupling rod nuts', 's16', 65, 0, true, '65 Nm, renew; counterhold on the joint stub’s multi-point socket (subframe overview).'],
  bolts_arm: ['Lower link to subframe bolts', 's18', 70, 180, true, '70 Nm + 180°, renew, tightened in the unladen position (lower suspension link overview).'],
  bolts_dsflange: ['Drive shaft flange bolts', 'p12', 70, 0, true, 'M10 multi-point bolts: diagonally to 10 Nm first, then diagonally to 70 Nm, renew (drive shaft VL107 overview; the smaller VL100 joint uses M8 at 40 Nm).'],
};
for (const [k, side] of [['fl', 'front-left'], ['fr', 'front-right']])
  for (const [id, [label, tool, nm, deg, renew, note, needOpen]] of Object.entries(CORNER))
    SPEC[id + '_' + k] = { label: `${label}, ${side}`, tool, nm, ...(deg ? { deg } : {}), renew, src: 'man', note, ...(needOpen ? { needOpen } : {}) };

/* fasteners for the real car's parts: bolt meshes where the hardware sits */
export function buildCarFasteners(byId, materialFactory) {
  const zinc = materialFactory(0xb8bec4, { metalness: .9, roughness: .32 }, 'brushed');
  const dark = materialFactory(0x2a2c2f, { metalness: .7, roughness: .45 }, 'brushed');
  const R = { y: [0, 0, 0], '-y': [Math.PI, 0, 0], x: [0, 0, -Math.PI / 2], '-x': [0, 0, Math.PI / 2], z: [Math.PI / 2, 0, 0], '-z': [-Math.PI / 2, 0, 0] };
  const boltGeo = {};
  const bolt = (g, p, dia, len, dir, mat = zinc) => {
    const k = dia + ':' + len;
    boltGeo[k] ||= (() => { const h = new THREE.CylinderGeometry(dia * .82, dia * .82, dia * .62, 6); h.translate(0, dia * .43, 0); const f = new THREE.CylinderGeometry(dia * 1.05, dia * 1.05, dia * .12, 20); f.translate(0, dia * .06, 0); const s = new THREE.CylinderGeometry(dia / 2, dia / 2, len, 12); s.translate(0, -len / 2, 0); return [h, f, s]; })();
    const b = new THREE.Group(); for (const gg of boltGeo[k]) { const m = new THREE.Mesh(gg, mat); m.castShadow = true; b.add(m); }
    b.rotation.set(...R[dir]); b.position.set(...p); g.add(b); return b;
  };
  const out = [];
  const set = (id, host, sys, fill) => { if (!byId[host]) return; const g = new THREE.Group(); g.name = id; fill(g, byId[host].box); out.push({ id, name: SPEC[id].label, sys, obj: g, host, tags: ['fastener'], qty: g.children.length, size: toolLabel(SPEC[id].tool), conf: SPEC[id].src === 'man' ? 'pub' : 'est', note: SPEC[id].note }); };
  for (const k of ['fl', 'fr', 'rl', 'rr']) set('fix_wheel_' + k, 'wheel_' + k, 'wheels', (g, b) => {
    const c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3()), sx = k[1] === 'l' ? 1 : -1, x = c.x + sx * (s.x / 2 - 0.045);
    for (let i = 0; i < 5; i++) { const a = i / 5 * Math.PI * 2 + Math.PI / 2; bolt(g, [x, c.y + Math.sin(a) * 0.056, c.z + Math.cos(a) * 0.056], 0.014, 0.03, sx > 0 ? 'x' : '-x'); }
  });
  // door hinge bolts: front-left positions measured on this model in Strip Bay (FIX), mirrored and estimated for the others
  const front = [[.832, 1.085, .745], [.832, 1.015, .745], [.838, .555, .845], [.838, .485, .845]];
  const rear = [[.812, 1.0, -.245], [.812, .935, -.245], [.818, .53, -.18], [.818, .465, -.18]];
  for (const [k, pts] of [['fl', front], ['fr', front], ['rl', rear], ['rr', rear]]) {
    const sx = k[1] === 'l' ? 1 : -1;
    set('fix_door_' + k, 'door_' + k, 'body', g => { for (const [x, y, z] of pts) bolt(g, [sx * x, y, z], 0.010, 0.04, sx > 0 ? 'x' : '-x'); });
  }
  set('fix_bonnet', 'panel_bonnet', 'body', g => { for (const sx of [1, -1]) for (const z of [1.125, 1.075]) bolt(g, [sx * 0.555, 0.958, z], 0.008, 0.025, 'y'); });
  set('fix_bumper_f', 'bumper_f', 'body', (g, b) => {
    for (const x of [-0.26, 0, 0.26]) bolt(g, [x, b.max.y - 0.065, b.max.z - 0.16], 0.007, 0.02, 'y', dark);   // to the lock carrier, under the bonnet's front edge
    for (const sx of [1, -1]) for (const dy of [0.06, -0.06]) bolt(g, [sx * (b.max.x - 0.035), (b.min.y + b.max.y) / 2 + dy, b.min.z + 0.07], 0.007, 0.02, sx > 0 ? 'x' : '-x', dark);
    for (const x of [-0.45, -0.15, 0.15, 0.45]) bolt(g, [x, b.min.y + 0.012, b.max.z - 0.2], 0.007, 0.02, '-y', dark);
  });
  return out;
}

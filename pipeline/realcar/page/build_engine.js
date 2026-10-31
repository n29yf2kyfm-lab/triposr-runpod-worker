// build_engine.js: one engine, part by part (an inline diesel to its published figures). Defines ENGINE for
// page/parts.html; the car page draws it in one piece in the car.
// ── the engine's figures (metres; x along the crank, the belt end at -x; y up; z across, exhaust at +z) ──
const D = CFG.dims;
const N = D.cylinders, B = D.bore, S = D.stroke, LR = D.rod, P = D.pitch, R = S / 2, HC = D.pin_to_crown;
const FIRE = D.firing;
const LB = N * P + 0.05, WB = Math.max(0.17, B * 2.39);
const XF = -LB / 2, XR = LB / 2;
const YD = R + LR + HC + 0.0005;                 // the deck: a piston at the top of its stroke just under it
const YB0 = R + 0.034;                           // the bores' bottom, clear of the counterweights' swing
const GASK = 0.0013, YH0 = YD + GASK, YH1 = YH0 + 0.105;
const ZV = -0.006;                               // the valves' row, under the camshaft
const FOLL = YH0 + 0.1225, CAMB = 0.0185, YC = FOLL + CAMB;   // followers' tops; the cam's base circle and axis
const XT = XF - 0.022, XA = XF - 0.066;           // the timing belt's plane, the accessory belt's
const YSUMP = -0.06;
const cxi = i => (i - (N - 1) / 2) * P;
const jourX = k => (k - N / 2) * P;
// each cylinder's power stroke: when the crank is at TDC_i (radians) it is at the top, firing
const TDC = Array.from({ length: N }, (_, i) => FIRE.indexOf(i + 1) * (4 * Math.PI / N));

const nth = ['1', '2', '3', '4', '5', '6'];
const cylName = i => `cylinder ${nth[i]}`;

// what the catalogue calls each kind (its part names), so a part carries the catalogue's OEM numbers
const CAT = {
  valve_ex: /exhaust valve$/i, valve_in: /(intake|inlet) valve$/i, spring: /valve spring$/i, keeper: /valve (keeper|cotter|collet)/i,
  retainer: /valve spring (retainer|cap)/i, stem_seal: /valve stem (seal|oil seal)/i, follower: /camshaft follower|lifter|tappet/i,
  cam: /^(engine )?camshaft$/i, cam_seal: /camshaft seal/i, cam_gear: /camshaft (gear|sprocket|pulley)/i, cam_cap: /camshaft (bearing )?cap/i,
  tbelt: /^(engine )?timing belt$/i, tensioner: /timing belt tensioner/i, idler: /timing belt idler|timing belt guide/i,
  oil_chain: /timing chain$|oil pump chain/i, chain_tens: /chain tensioner/i, head_gasket: /head gasket/i, head_bolt: /head bolt/i,
  head: /^(engine )?cylinder head$/i, cover_gasket: /(valve|cam(shaft)?|cylinder head) cover gasket/i, cam_cover: /valve cover$|camshaft cover$/i,
  filler_gasket: /oil filler cap gasket|filler cap seal/i, filler_cap: /oil filler cap$/i, dip_oring: /dipstick tube o-?ring|dipstick tube seal/i,
  dip_tube: /dipstick tube$/i, dipstick: /dipstick$/i, cooler_gasket: /oil cooler gasket|oil cooler seal/i, oil_cooler: /oil cooler$/i,
  filter_gasket: /oil filter (gasket|seal)|oil filter housing gasket/i, oil_filter: /^(engine )?oil filter$/i, filter_housing: /oil filter (housing|adapter)/i,
  coolant_hose: /(radiator )?coolant hose$|radiator hose$/i, hose_adapter: /coolant hose (adapter|flange)|coolant flange|water outlet|thermostat housing/i,
  water_pump: /water pump$/i, inj_pump: /injector pump|injection pump/i, injector: /fuel injector$|^injector$/i, glow: /glow plug$/i,
  intake_hose: /intake hose$|turbo(charger)? inlet hose/i, hose_sleeve: /hose sleeve|intake hose (seal|clamp)/i,
  alternator: /^alternator$/i, alt_pulley: /alternator pulley/i, ribbed: /serpentine belt|accessory drive belt$|v-?ribbed belt|drive belt$/i,
  acc_tensioner: /(accessory|drive) belt tensioner/i, turbo: /turbocharger$|^turbo$/i, egr_valve: /egr valve$|gas re-?circulation \(egr\) valve$/i,
  sump_gasket: /oil pan gasket|sump gasket/i, sump: /oil pan$|^sump$/i, drain_plug: /drain plug/i, oil_pump: /^(engine )?oil pump$/i,
  piston: /^(engine )?piston$/i, ring: /piston ring/i, gpin: /piston pin|wrist pin|gudgeon/i, rod: /connecting rod$/i,
  rod_shell: /(connecting )?rod bearing/i, main_shell: /main bearing$|crankshaft main bearing/i, thrust: /thrust washer|thrust bearing/i,
  crank: /^(engine )?crankshaft$/i, crank_seal: /crankshaft (seal|oil seal)|rear main seal/i, damper: /harmonic balancer|crankshaft pulley|vibration damper/i,
  crank_gear: /crankshaft (gear|sprocket)/i, flywheel: /flywheel|flexplate/i, exh_manifold: /exhaust manifold$/i, exh_gasket: /exhaust manifold gasket/i,
  intake_manifold: /intake manifold$/i, intake_gasket: /intake manifold gasket/i, glow_bus: /glow plug (bus|harness)/i,
};

const CHAIN = (CFG.construction || {}).timing === 'chain';
if (CHAIN) { CAT.tbelt = /^(engine )?timing chain$/i; CAT.tensioner = /timing chain tensioner/i; CAT.idler = /timing chain guide/i; CAT.oil_chain = /oil pump chain/i; }
// ── build the engine ──
function build() {
  const HEAD_W = WB, bores = Array.from({ length: N }, (_, i) => ({ x: cxi(i), z: 0, r: B / 2 + 0.0003 }));
  const journals = Array.from({ length: N + 1 }, (_, k) => jourX(k));

  // kinds: [key, name, group, off direction, distance]
  kind('ribbed', 'Accessory belt (ribbed)', 'Accessories', [-1, 0, 0], 0.16);
  kind('alternator', 'Alternator', 'Accessories', [0, 0, -1], 0.17);
  kind('alt_pulley', 'Alternator pulley', 'Accessories', [-1, 0, 0], 0.06);
  kind('acc_tensioner', 'Accessory belt tensioner', 'Accessories', [-1, 0, 0], 0.09);
  kind('tcover_up', 'Timing belt cover, upper', 'Belts and timing', [-1, 0.25, 0], 0.2);
  kind('tcover_low', 'Timing belt cover, lower', 'Belts and timing', [-1, -0.2, 0], 0.2);
  kind('damper_bolt', 'Crank pulley bolt', 'Belts and timing', [-1, 0, 0], 0.05);
  kind('damper', 'Crank pulley (vibration damper)', 'Belts and timing', [-1, 0, 0], 0.12);
  const drive = CHAIN ? 'chain' : 'belt';
  kind('tbelt', `Timing ${drive}`, 'Belts and timing', [-1, 0, 0], 0.13);
  kind('tensioner', `Timing ${drive} tensioner`, 'Belts and timing', [-1, 0, 0], 0.08);
  kind('idler', CHAIN ? 'Timing chain guide' : 'Timing belt idler', 'Belts and timing', [-1, 0, 0], 0.08);
  kind('cam_bolt', 'Camshaft sprocket bolt', 'Belts and timing', [-1, 0, 0], 0.04);
  kind('cam_gear', 'Camshaft sprocket', 'Belts and timing', [-1, 0, 0], 0.09);
  kind('pump_gear', 'Injection pump sprocket', 'Belts and timing', [-1, 0, 0], 0.09);
  kind('crank_gear', 'Crankshaft sprocket', 'Belts and timing', [-1, 0, 0], 0.05);
  kind('inj_pipe', 'Injector pipe', 'Fuel and glow plugs', [0, 1, 0], 0.17);
  kind('intake_hose', 'Intake hose', 'Air, turbo and exhaust', [0, 1, 0.3], 0.13);
  kind('hose_sleeve', 'Intake hose sleeve', 'Air, turbo and exhaust', [0, 1, 0.3], 0.03);
  kind('turbo', 'Turbo', 'Air, turbo and exhaust', [0, -0.2, 1], 0.13);
  kind('exh_nut', 'Exhaust manifold nut', 'Air, turbo and exhaust', [0, 0, 1], 0.05);
  kind('exh_manifold', 'Exhaust manifold', 'Air, turbo and exhaust', [0, 0, 1], 0.14);
  kind('exh_gasket', 'Exhaust manifold gasket', 'Air, turbo and exhaust', [0, 0, 1], 0.12);
  kind('egr_valve', 'EGR valve', 'Air, turbo and exhaust', [0, 0.4, -1], 0.1);
  kind('intake_manifold', 'Intake manifold', 'Air, turbo and exhaust', [0, 0, -1], 0.14);
  kind('intake_gasket', 'Intake manifold gasket', 'Air, turbo and exhaust', [0, 0, -1], 0.12);
  kind('cover_nut', 'Cam cover nut', 'Cylinder head', [0, 1, 0], 0.05);
  kind('filler_cap', 'Oil filler cap', 'Lubrication', [0, 1, 0], 0.08);
  kind('filler_gasket', 'Oil filler cap seal', 'Lubrication', [0, 1, 0], 0.03);
  kind('cam_cover', 'Cam cover', 'Cylinder head', [0, 0.7, 1], 0.26);
  kind('cover_gasket', 'Cam cover gasket', 'Cylinder head', [0, 0.8, 1], 0.2);
  kind('inj_clamp_bolt', 'Injector clamp bolt', 'Fuel and glow plugs', [0, 1, 0], 0.04);
  kind('inj_clamp', 'Injector clamp', 'Fuel and glow plugs', [0, 1, 0], 0.06);
  kind('injector', 'Injector', 'Fuel and glow plugs', [0, 1, 0], 0.12);
  kind('glow_bus', 'Glow plug bus bar', 'Fuel and glow plugs', [0, 0.3, 1], 0.06);
  kind('glow', 'Glow plug', 'Fuel and glow plugs', [0, 1, 0], 0.1);
  kind('coolant_hose', 'Coolant hose', 'Cooling', [1, 0, 0], 0.1);
  kind('hose_adapter', 'Coolant flange', 'Cooling', [1, 0, 0], 0.11);
  kind('head_bolt', 'Cylinder head bolt', 'Cylinder head', [0, 1, 0], 0.26);
  kind('head', 'Cylinder head', 'Cylinder head', [0, 0.75, 1], 0.34);
  kind('head_gasket', 'Head gasket', 'Cylinder head', [0, 1, 0], 0.16);
  kind('cap_nut', 'Camshaft bearing cap nut', 'Valvetrain', [0, 1, 0], 0.04);
  kind('cam_cap', 'Camshaft bearing cap', 'Valvetrain', [0, 1, 0], 0.18);
  kind('cam_seal', 'Camshaft seal', 'Valvetrain', [-1, 0, 0], 0.06);
  kind('cam', 'Camshaft', 'Valvetrain', [0, 1, 0], 0.14);
  kind('follower', 'Cam follower (hydraulic)', 'Valvetrain', [0, 1, 0], 0.12);
  kind('keeper', 'Valve keeper (collet)', 'Valvetrain', [0, 1, 0], 0.09);
  kind('retainer', 'Valve spring cap', 'Valvetrain', [0, 1, 0], 0.075);
  kind('spring', 'Valve spring', 'Valvetrain', [0, 1, 0], 0.05);
  kind('stem_seal', 'Valve stem seal', 'Valvetrain', [0, 1, 0], 0.03);
  kind('valve_in', 'Intake valve', 'Valvetrain', [0, -1, 0], 0.14);
  kind('valve_ex', 'Exhaust valve', 'Valvetrain', [0, -1, 0], 0.14);
  kind('drain_plug', 'Sump drain plug', 'Lubrication', [0, -1, 0], 0.05);
  kind('sump_bolt', 'Sump bolt', 'Lubrication', [0, -1, 0], 0.06);
  kind('sump', 'Sump (oil pan)', 'Lubrication', [0, -0.55, 1], 0.32);
  kind('sump_gasket', 'Sump gasket', 'Lubrication', [0, -1, 0], 0.12);
  kind('chain_tens', 'Oil pump chain tensioner', 'Lubrication', [0, -1, 0], 0.07);
  kind('oil_chain', 'Oil pump chain', 'Lubrication', [0, -1, 0], 0.09);
  kind('oil_pump', 'Oil pump and pick-up', 'Lubrication', [0, -1, 0], 0.12);
  kind('rod_bolt', 'Big-end bolt', 'Pistons and rods', [0, -1, 0], 0.04);
  kind('rod_cap', 'Big-end cap', 'Pistons and rods', [0, -1, 0], 0.09);
  kind('rod_shell', 'Big-end bearing shell', 'Pistons and rods', [0, -1, 0], 0.03);
  kind('piston', 'Piston', 'Pistons and rods', [0, 1, 0], 0.42);
  kind('ring', 'Piston ring', 'Pistons and rods', [0, 1, 0], 0.03);
  kind('circlip', 'Piston pin circlip', 'Pistons and rods', [0, 0, 1], 0.05);
  kind('gpin', 'Piston pin', 'Pistons and rods', [0, 0, 1], 0.08);
  kind('rod', 'Connecting rod', 'Pistons and rods', [0, -1, 0], 0.13);
  kind('fly_bolt', 'Flywheel bolt', 'Block and bottom end', [1, 0, 0], 0.05);
  kind('flywheel', 'Flywheel (dual-mass)', 'Block and bottom end', [1, 0, 0], 0.16);
  kind('oil_filter', 'Oil filter', 'Lubrication', [0, -1, 0], 0.08);
  kind('filter_gasket', 'Oil filter seal', 'Lubrication', [0, -1, 0], 0.02);
  kind('oil_cooler', 'Oil cooler', 'Lubrication', [0, -1, 0], 0.05);
  kind('cooler_gasket', 'Oil cooler gasket', 'Lubrication', [0, -1, 0], 0.025);
  kind('filter_housing', 'Oil filter housing', 'Lubrication', [0, 0, -1], 0.12);
  kind('dipstick', 'Dipstick', 'Lubrication', [0, 1, 0], 0.14);
  kind('dip_tube', 'Dipstick tube', 'Lubrication', [0, 1, 0], 0.1);
  kind('dip_oring', 'Dipstick tube O-ring', 'Lubrication', [0, 1, 0], 0.02);
  kind('water_pump', 'Water pump', 'Cooling', [-1, 0, 0], 0.1);
  kind('inj_pump', 'Injection pump', 'Fuel and glow plugs', [0, 0, -1], 0.16);
  kind('crank_seal', 'Crankshaft oil seal', 'Block and bottom end', [-1, 0, 0], 0.06);
  kind('main_bolt', 'Main bearing cap bolt', 'Block and bottom end', [0, -1, 0], 0.05);
  kind('main_cap', 'Main bearing cap', 'Block and bottom end', [0, -1, 0], 0.12);
  kind('main_shell', 'Main bearing shell', 'Block and bottom end', [0, -1, 0], 0.03);
  kind('thrust', 'Crankshaft thrust washer', 'Block and bottom end', [0, -1, 0], 0.08);
  kind('crank', 'Crankshaft', 'Block and bottom end', [0, -1, -0.3], 0.3);
  kind('block', 'Cylinder block', 'Block and bottom end', [0, 0, 0], 0);

  // ── the block (stays put) ──
  {
    // the bores' part, its edges rounded and the bores' tops chamfered; the deck on top is machined flat
    const parts = [slabY(XF, -WB / 2, XR, WB / 2, YB0, YD, 0.0025, 0.007, bores)];
    // the crankcase skirt, a little proud of the bores' part, down to the sump rail
    const sk = WB / 2 + 0.004;
    for (const s of [-1, 1]) parts.push(slabY(XF, s * sk - 0.005, XR, s * sk + 0.005, YSUMP + 0.008, YB0 + 0.006, 0.002, 0.004));
    for (const [x0, ex] of [[XF, 0.012], [XR - 0.012, 0.012]])
      parts.push(extrudeX(zyShape(rect(-WB / 2, YSUMP, WB / 2, YB0), [{ z: 0, y: 0, r: 0.031 }]), ex, x0));
    {   // the sump rail, a flange all round the bottom
      const rail = xzShape(rrect(LB + 0.004, 2 * sk + 0.02, 0.006));
      rail.holes.push(new THREE.Path(rect(XF + 0.012, -WB / 2 + 0.006, XR - 0.012, WB / 2 - 0.006).map(([x, z]) => V2(x, -z))));
      parts.push(extrudeY(rail, 0.012, YSUMP, { curveSegments: 6 }));
    }
    for (const x of journals) {   // bulkheads, the upper half of each main bearing
      const zm = WB / 2 - 0.008;
      const out = [[zm, 0], [zm, YB0], [-zm, YB0], [-zm, 0], ...arcPts(0, 0, 0.0285, Math.PI, 0, 14)];
      parts.push(extrudeX(zyShape(out), 0.02, x - 0.01));
    }
    // ribs up the bores' part and the skirt at each bulkhead, a raised water jacket line, the water pump's
    // housing, an engine-number pad
    for (const s of [-1, 1]) for (let i = 0; i <= N; i++) {
      const x = jourX(i), z0 = s > 0 ? WB / 2 - 0.002 : -WB / 2 - 0.006;
      parts.push(slabY(x - 0.0045, z0, x + 0.0045, z0 + 0.008, YB0 + 0.004, YD - 0.012, 0.002));
      const z1 = s > 0 ? sk + 0.003 : -sk - 0.009;
      parts.push(slabY(x - 0.005, z1, x + 0.005, z1 + 0.006, YSUMP + 0.012, YB0 + 0.004, 0.002));
    }
    for (const s of [-1, 1]) { const z0 = s > 0 ? WB / 2 - 0.002 : -WB / 2 - 0.004; parts.push(slabY(XF + 0.004, z0, XR - 0.004, z0 + 0.006, YD - 0.024, YD - 0.012, 0.0018)); }
    parts.push(slabX(XF - 0.012, XF + 0.001, 0.045, 0.095, 0.095, 0.145, 0.003, 0.01), slabY(XF + 0.03, -WB / 2 - 0.007, XF + 0.09, -WB / 2 + 0.002, YD - 0.045, YD - 0.026, 0.0015));
    // core plugs, a cylinder each, both sides
    const plugs = [];
    for (let i = 0; i < N; i++) for (const s of [-1, 1]) {
      const g = latheY([[0.0001, 0], [0.0125, 0], [0.0125, 0.003], [0.0105, 0.0042], [0.0001, 0.0038]], 28); g.rotateX(s * Math.PI / 2);
      plugs.push(g.translate(cxi(i), 0.155, s * (WB / 2 - 0.001)));
    }
    add('block', 'Cylinder block', group([merge(parts), M.iron], [merge(plugs), M.forged]));
  }

  // ── crankshaft, its sprockets and seals ──
  const crankAnim = p => a => { p.obj.rotation.x = a; };
  let crank;
  {
    const parts = [];
    for (const x of journals) parts.push(cylX(0.0268, 0.024, x - 0.012, 0, 0, 28));
    for (let i = 0; i < N; i++) {
      const a = -TDC[i], pz = R * Math.sin(a), py = R * Math.cos(a), x = cxi(i);
      parts.push(cylX(0.024, 0.026, x - 0.013, py, pz, 24));
      for (const side of [-1, 1]) {
        const wx = x + side * 0.022 - 0.009;
        const far = [], near = [];
        const dirA = Math.atan2(py, pz);     // the pin's direction in (z, y)
        for (let k = 0; k <= 12; k++) { const t = dirA + Math.PI / 2 + Math.PI * k / 12; far.push([0.03 * Math.cos(t), 0.03 * Math.sin(t)]); }
        for (let k = 0; k <= 12; k++) { const t = dirA - Math.PI / 2 + Math.PI * k / 12; near.push([pz + 0.027 * Math.cos(t), py + 0.027 * Math.sin(t)]); }
        parts.push(extrudeX(zyShape([...far, ...near]), 0.018, wx));
        const cw = [[0, 0]];
        for (let k = 0; k <= 16; k++) { const t = dirA + Math.PI - 1.05 + 2.1 * k / 16; cw.push([0.072 * Math.cos(t), 0.072 * Math.sin(t)]); }
        parts.push(extrudeX(zyShape(cw), 0.018, wx));
      }
    }
    parts.push(cylX(0.02, jourX(0) - 0.012 - (XA - 0.014), XA - 0.014, 0, 0, 20));      // the nose
    parts.push(cylX(0.045, 0.012, XR + 0.002, 0, 0, 32), cylX(0.026, XR + 0.002 - jourX(N) - 0.012, jourX(N) + 0.012, 0, 0, 24));
    // the oil pump's chain sprocket, inside the front wall
    parts.push(sprocketG(0.025, 20, 0.008).translate(XF + 0.024, 0, 0));
    crank = add('crank', 'Crankshaft', mesh(merge(parts), M.forged));
    crank.anim = crankAnim(crank);
  }
  const crankGear = add('crank_gear', 'Crankshaft sprocket (timing belt)', mesh(sprocketG(0.032, 19, 0.026).translate(XT, 0, 0), M.steel), { parent: crank });
  crankGear.anim = crankAnim(crankGear);
  add('crank_seal', 'Crankshaft oil seal, belt end', mesh(torusX(0.026, 0.005, XF - 0.004), M.rubber), { dir: [-1, 0, 0] });
  add('crank_seal', 'Crankshaft oil seal, flywheel end', mesh(torusX(0.026, 0.005, XR + 0.002), M.rubber), { dir: [1, 0, 0] });
  // main caps, their bolts and shells; thrust washers
  for (let k = 0; k <= N; k++) {
    const x = journals[k];
    const out = [[0.048, 0], [0.0285, 0], ...arcPts(0, 0, 0.0285, 0, -Math.PI, 14), [-0.0285, 0], [-0.048, 0], [-0.048, -0.05], [0.048, -0.05]];
    const cap = add('main_cap', `Main bearing cap ${k + 1}`, mesh(extrudeX(zyShape(out), 0.022, x - 0.011), M.ironDark));
    for (const z of [-0.036, 0.036]) {
      const g = boltG(0.075, 0.011, 12, false); g.rotateX(Math.PI);
      add('main_bolt', `Main bearing cap bolt, cap ${k + 1}`, mesh(g, M.bolt), { parent: cap, pos: [x, -0.05, z] });
    }
    const low = new THREE.CylinderGeometry(0.0271, 0.0271, 0.02, 24, 1, true, 0, Math.PI); low.rotateZ(-Math.PI / 2); low.translate(x, 0, 0);
    add('main_shell', `Main bearing shell ${k + 1}, lower`, mesh(low, M.brass), { parent: cap, dist: 0.02 });
    const upS = new THREE.CylinderGeometry(0.0271, 0.0271, 0.02, 24, 1, true, Math.PI, Math.PI); upS.rotateZ(-Math.PI / 2); upS.translate(x, 0, 0);
    add('main_shell', `Main bearing shell ${k + 1}, upper`, mesh(upS, M.brass), { dir: [0, 1, 0], dist: 0.03 });
    if (k === Math.floor(N / 2)) for (const s of [-1, 1]) {
      const g = extrudeX(zyShape([...arcPts(0, 0, 0.042, 0, -Math.PI, 16), ...arcPts(0, 0, 0.029, -Math.PI, 0, 16)]), 0.0025, x + s * 0.0125 - 0.00125);
      add('thrust', `Crankshaft thrust washer, ${s < 0 ? 'belt' : 'flywheel'} side`, mesh(g, M.brass), { parent: cap });
    }
  }

  // ── pistons, rods, rings, pins ──
  const pinY = th => R * Math.cos(th) + Math.sqrt(LR * LR - (R * Math.sin(th)) ** 2);
  const pistonG = latheY([[0.0001, -0.002], [0.033, -0.002], [0.033, -0.024], [B / 2 - 0.0006, -0.024], [B / 2 - 0.0003, HC - 0.007],
    [B / 2 - 0.0003, HC], [0.023, HC], [0.016, HC - 0.007], [0.012, HC - 0.013], [0.004, HC - 0.011], [0.0001, HC - 0.0105]], 40);
  const rodOut = [[0.036, 0], [0.033, 0.02], [0.014, LR - 0.022], ...arcPts(0, LR, 0.0175, -0.95, Math.PI + 0.95, 20),
    [-0.014, LR - 0.022], [-0.033, 0.02], [-0.036, 0], [-0.0255, 0], ...arcPts(0, 0, 0.0255, Math.PI, 0, 16), [0.0255, 0]];
  const rodG = extrudeX(zyShape(rodOut, [{ z: 0, y: LR, r: 0.0128 }]), 0.022, -0.011);
  const capOut = [[0.036, 0], [0.0255, 0], ...arcPts(0, 0, 0.0255, 0, -Math.PI, 16), [-0.0255, 0], [-0.036, 0], ...arcPts(0, 0, 0.036, Math.PI + 0.25, TAU - 0.25, 14)];
  const capG = extrudeX(zyShape(capOut), 0.022, -0.011);
  for (let i = 0; i < N; i++) {
    const x = cxi(i), c = cylName(i);
    const th = a => a - TDC[i];
    const pistonPos = (p, a) => p.base.set(x, pinY(th(a)), 0);
    const rodMove = (p, a) => { const t = th(a); p.base.set(x, R * Math.cos(t), R * Math.sin(t)); p.obj.rotation.x = -Math.asin(R * Math.sin(t) / LR); };
    const pis = add('piston', `Piston, ${c}`, mesh(pistonG, M.piston)); pis.anim = a => pistonPos(pis, a);
    const ringsAt = [[HC - 0.006, 0.0011, 'top compression ring'], [HC - 0.0115, 0.0011, 'second compression ring'], [HC - 0.018, 0.0014, 'oil control ring']];
    for (const [y, tube, nm] of ringsAt) {
      const r = add('ring', `Piston ring, ${c}: ${nm}`, mesh(torusY(B / 2 - 0.0004, tube, 0, y, 0), M.bolt), { parent: pis, dist: 0.03 + (HC - y) * 2 });
      r.anim = a => pistonPos(r, a);
    }
    const gp = add('gpin', `Piston pin, ${c}`, mesh(cylZ(0.0125, 0.062, -0.031, 0, 0, 20), M.steel), { parent: pis }); gp.anim = a => pistonPos(gp, a);
    for (const s of [-1, 1]) {
      const g = new THREE.TorusGeometry(0.0112, 0.0009, 6, 20); g.translate(0, 0, s * 0.0305);
      const cl = add('circlip', `Piston pin circlip, ${c}`, mesh(g, M.steel), { parent: pis, dir: [0, 0, s] }); cl.anim = a => pistonPos(cl, a);
    }
    const rod = add('rod', `Connecting rod, ${c}`, mesh(rodG, M.forged), { parent: pis }); rod.anim = a => rodMove(rod, a);
    const shU = new THREE.CylinderGeometry(0.0253, 0.0253, 0.019, 24, 1, true, Math.PI, Math.PI); shU.rotateZ(-Math.PI / 2);
    const su = add('rod_shell', `Big-end bearing shell, ${c}, upper`, mesh(shU, M.brass), { parent: rod, dir: [0, 1, 0], dist: 0.03 }); su.anim = a => rodMove(su, a);
    const cap = add('rod_cap', `Big-end cap, ${c}`, mesh(capG, M.forged), { parent: rod }); cap.anim = a => rodMove(cap, a);
    const shL = new THREE.CylinderGeometry(0.0253, 0.0253, 0.019, 24, 1, true, 0, Math.PI); shL.rotateZ(-Math.PI / 2);
    const sl = add('rod_shell', `Big-end bearing shell, ${c}, lower`, mesh(shL, M.brass), { parent: cap }); sl.anim = a => rodMove(sl, a);
    for (const z of [-0.0305, 0.0305]) {
      const g = boltG(0.045, 0.009, 12, false); g.rotateX(Math.PI); g.translate(0, -0.026, z);
      const b = add('rod_bolt', `Big-end bolt, ${c}`, mesh(g, M.bolt), { parent: cap }); b.anim = a => rodMove(b, a);
    }
  }

  // ── flywheel ──
  {
    const disc = latheX([[0.03, 0], [0.135, 0], [0.135, 0.012], [0.12, 0.014], [0.12, 0.018], [0.135, 0.02], [0.135, 0.03], [0.03, 0.03]], 64);
    disc.translate(XR + 0.014, 0, 0);
    const teeth = [];
    for (let k = 0; k < 132; k++) { const a = k / 132 * TAU, t = new THREE.BoxGeometry(0.01, 0.007, 0.0045); t.rotateX(a); t.translate(XR + 0.039, 0.1385 * Math.cos(a), 0.1385 * Math.sin(a)); teeth.push(t); }
    const fly = add('flywheel', 'Flywheel (dual-mass)', group([disc, M.ironDark], [merge(teeth), M.steel]), { parent: crank });
    fly.anim = crankAnim(fly);
    for (let k = 0; k < 8; k++) {
      const a = k / 8 * TAU, g = boltG(0.022, 0.009, 12, false); g.rotateZ(-Math.PI / 2); g.translate(XR + 0.046, 0.026 * Math.cos(a), 0.026 * Math.sin(a));
      const b = add('fly_bolt', 'Flywheel bolt', mesh(g, M.bolt), { parent: fly }); b.anim = crankAnim(b);
    }
  }

  // ── oil pump, its chain and tensioner; sump ──
  {
    const pump = add('oil_pump', 'Oil pump and pick-up', group(
      [merge(box(0.045, 0.04, 0.07, XF + 0.045, -0.118, 0.0), sprocketG(0.03, 24, 0.008).translate(XF + 0.024, -0.118, 0)), M.aluCast],
      [merge(tubeG([[XF + 0.06, -0.135, 0.02], [XF + 0.1, -0.15, 0.03], [XF + 0.16, -0.153, 0.02]], 0.007, 20, 8),
        cylY(0.026, 0.004, -0.158, XF + 0.165, 0.02, 24)), M.steel]));
    const path = beltPath([{ z: 0, y: -0.118, r: 0.03 }, { z: 0.0392, y: -0.058, r: -0.0135 }, { z: 0, y: 0, r: 0.025 }]);
    add('oil_chain', 'Oil pump chain', mesh(chainG(path, XF + 0.024), M.chain));
    add('chain_tens', 'Oil pump chain tensioner', mesh(merge(cylX(0.0115, 0.01, XF + 0.019, -0.058, 0.0392, 18), box(0.01, 0.05, 0.012, XF + 0.024, -0.075, 0.056)), M.steel));
    void pump;
  }
  const sumpW = WB + 0.008;
  // cast aluminium: its flange, the pan, the deeper well the pick-up sits in, ribs down the sides and under it
  const wx0 = -LB * 0.2 - LB * 0.25 - 0.008, wx1 = -LB * 0.2 + LB * 0.25 + 0.008;
  const sumpParts = [slabY(XF - 0.004, -sumpW / 2 - 0.012, XR + 0.004, sumpW / 2 + 0.012, YSUMP - 0.0065, YSUMP - 0.0015, 0.0015, 0.008),
    slabY(XF - 0.002, -sumpW / 2 - 0.004, XR + 0.002, sumpW / 2 + 0.004, -0.157, YSUMP - 0.004, 0.008, 0.03, [], 0.011, 4),
    slabY(wx0, -sumpW * 0.4 - 0.008, wx1, sumpW * 0.4 + 0.008, -0.193, -0.14, 0.01, 0.03, [], 0.012, 4)];
  for (let k = 0; k < 7; k++) for (const s of [-1, 1]) {
    const x = XF + 0.03 + k * (LB - 0.06) / 6, z0 = s > 0 ? sumpW / 2 + 0.002 : -sumpW / 2 - 0.0065;
    sumpParts.push(slabY(x - 0.004, z0, x + 0.004, z0 + 0.0045, -0.146, YSUMP - 0.012, 0.0012));
  }
  for (const z of [-0.05, -0.025, 0.025, 0.05]) sumpParts.push(slabY(wx0 + 0.02, z - 0.003, wx1 - 0.02, z + 0.003, -0.198, -0.188, 0.002));
  const sump = add('sump', 'Sump (oil pan)', mesh(merge(sumpParts), M.aluCast));
  add('drain_plug', 'Sump drain plug', mesh(merge(boltG(0.012, 0.014, 6, true).rotateX(Math.PI).translate(XF + 0.06, -0.195, 0)), M.zinc), { parent: sump });
  {
    const ring = [...rect(XF - 0.002, -sumpW / 2 - 0.01, XR + 0.002, sumpW / 2 + 0.01)];
    const holeShape = xzShape(ring); const inner = new THREE.Path(rect(XF + 0.008, -WB / 2 + 0.008, XR - 0.008, WB / 2 - 0.008).map(([x, z]) => V2(x, -z))); holeShape.holes.push(inner);
    add('sump_gasket', 'Sump gasket', mesh(extrudeY(holeShape, 0.0015, YSUMP - 0.0015), M.fibre));
    const pos = [];
    for (let k = 0; k < 7; k++) { const x = XF + 0.02 + (LB - 0.04) * k / 6; pos.push([x, sumpW / 2 + 0.005], [x, -sumpW / 2 - 0.005]); }
    pos.push([XF + 0.004, 0.05], [XF + 0.004, -0.05], [XR - 0.004, 0.05], [XR - 0.004, -0.05]);
    for (const [x, z] of pos) {
      const gb = boltG(0.02, 0.006, 6, true); gb.rotateX(Math.PI);
      add('sump_bolt', 'Sump bolt', mesh(gb, M.bolt), { parent: sump, pos: [x, YSUMP - 0.0065, z] });
    }
  }

  // ── cylinder head ──
  let head;
  {
    const parts = [];
    parts.push(slabY(XF, -HEAD_W / 2, XR, HEAD_W / 2, YH0, YH0 + 0.058, 0.0022, 0.006));             // the deck and ports
    const wall = xzShape(rrect(LB, HEAD_W, 0.006));
    wall.holes.push(new THREE.Path(rrect(LB - 0.018, HEAD_W - 0.018, 0.004).map(([x, z]) => V2(x, -z))));
    parts.push(extrudeY(wall, YH1 - YH0 - 0.058 - 0.008, YH0 + 0.058, { curveSegments: 6 }));
    {   // the cover's joint face, a lip proud of the walls, machined flat
      const bv = 0.0012, lip = xzShape(rrect(LB + 0.006 - 2 * bv, HEAD_W + 0.006 - 2 * bv, 0.009));
      lip.holes.push(new THREE.Path(rrect(LB - 0.018 + 2 * bv, HEAD_W - 0.018 + 2 * bv, 0.004).map(([x, z]) => V2(x, -z))));
      parts.push(extrudeY(lip, 0.008 - 2 * bv, YH1 - 0.008 + bv, { bevelEnabled: true, bevelThickness: bv, bevelSize: bv, bevelSegments: 2, curveSegments: 6 }));
    }
    // a cast bead along each side between the ports, and the lifting eyes on the ends
    for (const s of [-1, 1]) parts.push(slabY(XF + 0.006, s * HEAD_W / 2 - 0.004, XR - 0.006, s * HEAD_W / 2 + 0.004, YH0 + 0.062, YH0 + 0.072, 0.0025));
    for (const [x, z] of [[XF - 0.004, 0.05], [XR + 0.004, -0.05]]) {
      const eye = zyShape(rrect(0.036, 0.04, 0.012).map(([a, b]) => [a + z, b + YH1 + 0.012]), [{ z, y: YH1 + 0.022, r: 0.007 }]);
      parts.push(extrudeX(eye, 0.008, x - 0.004, 12));
    }
    const vx = [];
    for (let i = 0; i < N; i++) vx.push(cxi(i) - 0.0185, cxi(i) + 0.0185);
    parts.push(extrudeY(xzShape(rect(XF + 0.012, ZV - 0.025, XR - 0.012, ZV + 0.025), vx.map(x => ({ x, z: ZV, r: 0.0178 }))), YH1 - (YH0 + 0.085), YH0 + 0.085));
    for (const x of journals) {   // the camshaft's saddles
      const out = [[ZV + 0.022, YH1], [ZV + 0.022, YC], [ZV + 0.013, YC], ...arcPts(ZV, YC, 0.013, 0, -Math.PI, 12), [ZV - 0.022, YC], [ZV - 0.022, YH1]];
      parts.push(extrudeX(zyShape(out), 0.018, x - 0.009));
    }
    for (const x of journals) for (const z of [-0.062, 0.062]) parts.push(cylY(0.012, 0.017, YH0 + 0.058, x, z, 20));   // head-bolt bosses
    for (let i = 0; i < N; i++) {      // ports: intake on -z, exhaust on +z
      parts.push(slabZ(-HEAD_W / 2 - 0.012, -HEAD_W / 2 + 0.002, cxi(i) - 0.019, cxi(i) + 0.019, YH0 + 0.013, YH0 + 0.048, 0.002, 0.007),
        slabZ(HEAD_W / 2 - 0.002, HEAD_W / 2 + 0.012, cxi(i) - 0.019, cxi(i) + 0.019, YH0 + 0.017, YH0 + 0.053, 0.002, 0.007));
    }
    head = add('head', 'Cylinder head', mesh(merge(parts), M.aluCast));
  }
  {
    // head gasket: the bores, the bolts and the water ways
    const holes = [...bores.map(b => ({ x: b.x, z: 0, r: B / 2 + 0.0015 }))];
    for (const x of journals) for (const z of [-0.062, 0.062]) holes.push({ x, z, r: 0.0065 });
    for (let i = 0; i < N; i++) for (const z of [-0.07, 0.07]) holes.push({ x: cxi(i), z, r: 0.004 });
    add('head_gasket', 'Head gasket (multi-layer steel)', mesh(extrudeY(xzShape(rect(XF + 0.002, -WB / 2 + 0.002, XR - 0.002, WB / 2 - 0.002), holes), GASK, YD), M.gasket));
  }
  for (let k = 0; k <= N; k++) for (const z of [-0.062, 0.062]) {
    const g = boltG(0.165, 0.012, 12, true);
    add('head_bolt', `Cylinder head bolt, ${z < 0 ? 'intake' : 'exhaust'} side, ${k + 1} of ${N + 1}`, mesh(g, M.bolt), { parent: head, pos: [journals[k], YH0 + 0.075, z] });
  }

  // ── valvetrain ──
  const camRotate = (p, a) => { p.obj.rotation.x = a / 2; };
  // when each valve is open the most (crank radians), and the lobe that does it
  const NOSE = 1.15, LIFT = 0.0095;
  const lift = phi => { const f = Math.abs(((phi + Math.PI) % TAU + TAU) % TAU - Math.PI); return f < NOSE ? LIFT * Math.cos(Math.PI / 2 * f / NOSE) ** 2 : 0; };
  const valves = [];
  for (let i = 0; i < N; i++) {
    valves.push({ i, x: cxi(i) - 0.0185, key: 'valve_in', what: 'intake', r: 0.0177, max: TDC[i] + Math.PI * 2 + 1.88 });
    valves.push({ i, x: cxi(i) + 0.0185, key: 'valve_ex', what: 'exhaust', r: 0.0155, max: TDC[i] + Math.PI * 2 - 1.92 });
  }
  for (const v of valves) v.lobe = Math.PI - v.max / 2;   // the lobe's nose, in the camshaft's own turn
  const liftAt = (v, a) => lift(v.lobe + a / 2 - Math.PI);
  let cam;
  {
    const parts = [cylX(0.012, XR - 0.01 - (XF - 0.04), XF - 0.04, 0, 0, 20)];
    for (const x of journals) parts.push(cylX(0.013, 0.02, x - 0.01, 0, 0, 24));
    for (const v of valves) {
      const pts = [];
      for (let k = 0; k < 64; k++) { const phi = k / 64 * TAU - Math.PI, a = v.lobe + phi, r = CAMB + lift(phi); pts.push([r * Math.sin(a), r * Math.cos(a)]); }
      parts.push(extrudeX(zyShape(pts), 0.015, v.x - 0.0075, 4));
    }
    cam = add('cam', 'Camshaft', mesh(merge(parts), M.forged), { parent: head, pos: [0, YC, ZV] });
    cam.anim = a => camRotate(cam, a);
  }
  add('cam_seal', 'Camshaft seal', mesh(torusX(0.02, 0.0045, XF - 0.004, YC, ZV), M.rubber), { parent: head });
  for (let k = 0; k <= N; k++) {
    const x = journals[k];
    const out = [[ZV + 0.022, YC], [ZV + 0.013, YC], ...arcPts(ZV, YC, 0.013, 0, Math.PI, 12), [ZV - 0.022, YC], [ZV - 0.022, YC + 0.016], [ZV + 0.022, YC + 0.016]];
    const capP = add('cam_cap', `Camshaft bearing cap ${k + 1}`, mesh(merge(extrudeX(zyShape(out), 0.018, x - 0.009), box(0.012, 0.004, 0.034, x, YC + 0.018, ZV)), M.aluCast), { parent: head });
    for (const s of [-1, 1]) add('cap_nut', `Camshaft bearing cap nut, cap ${k + 1}`, mesh(merge(nutG(0.008), cylY(0.004, 0.012, -0.004)), M.bolt), { parent: capP, pos: [x, YC + 0.016, ZV + s * 0.0175] });
  }
  const valveG = r => latheY([[0.0001, 0], [r, 0], [r, 0.0016], [r - 0.0022, 0.0038], [0.0055, 0.011], [0.0036, 0.019], [0.0035, 0.0965], [0.0001, 0.0965]], 28);
  const followerG = merge(latheY([[0.0001, 0.026], [0.0174, 0.026], [0.0174, 0.002], [0.0166, 0], [0.012, 0], [0.012, 0.004], [0.0001, 0.004]], 32));
  const springBase = YH0 + 0.058, springLen = 0.0315;
  for (const v of valves) {
    const c = cylName(v.i), where = `${c}, ${v.what}`;
    const vp = add(v.key, `${v.what === 'intake' ? 'Intake' : 'Exhaust'} valve, ${c}`, mesh(valveG(v.r), M.steel), { parent: head });
    vp.anim = a => vp.base.set(v.x, YH0 + 0.0006 - liftAt(v, a), ZV);
    add('stem_seal', `Valve stem seal, ${where}`, mesh(merge(cylY(0.0062, 0.009, 0), torusY(0.0058, 0.0009, 0, 0.007, 0)), M.seal), { parent: head, pos: [v.x, springBase, ZV] });
    const sp = add('spring', `Valve spring, ${where}`, mesh(springG(0.0118, springLen, 0.0034, 6.5), M.steel), { parent: head, pos: [v.x, springBase, ZV] });
    sp.anim = a => { sp.obj.scale.y = (springLen - liftAt(v, a)) / springLen; };
    const rt = add('retainer', `Valve spring cap, ${where}`, mesh(latheY([[0.004, 0], [0.0145, 0.0006], [0.0145, 0.0026], [0.006, 0.0038], [0.004, 0.0038]], 28), M.steel), { parent: head });
    rt.anim = a => rt.base.set(v.x, springBase + springLen - liftAt(v, a), ZV);
    for (const s of [0, 1]) {
      const g = new THREE.CylinderGeometry(0.0046, 0.0056, 0.0068, 12, 1, false, s * Math.PI + 0.06, Math.PI - 0.12); g.translate(0, 0.0034, 0);
      const kp = add('keeper', `Valve keeper, ${where}, ${s ? 'second' : 'first'} half`, mesh(g, M.bolt), { parent: head });
      kp.anim = a => kp.base.set(v.x, YH0 + 0.0885 - liftAt(v, a), ZV);
    }
    const fo = add('follower', `Cam follower, ${where}`, mesh(followerG, M.steel), { parent: head });
    fo.anim = a => fo.base.set(v.x, FOLL - 0.026 - liftAt(v, a), ZV);
  }
  // the camshaft's sprocket and bolt
  const camGear = add('cam_gear', 'Camshaft sprocket', mesh(sprocketG(0.0645, 38, 0.026, 6), M.steel), { parent: head, pos: [XT, YC, ZV] });
  camGear.anim = a => camRotate(camGear, a);
  { const g = boltG(0.03, 0.012, 6, true); g.rotateZ(Math.PI / 2); const b = add('cam_bolt', 'Camshaft sprocket bolt', mesh(g, M.bolt), { parent: camGear, pos: [XT - 0.02, YC, ZV] }); b.anim = a => camRotate(b, a); }

  // ── cam cover, its gasket and nuts; the oil filler cap ──
  {
    // cast aluminium: a flange on the gasket, a domed body, two beads along the top carrying the nuts' bosses,
    // the filler neck at the front and the crankcase breather at the back
    const CW = 0.144, CL = LB - 0.012, y0 = YH1 + 0.004, NZ = 0.042;
    const alu = [slabY(-CL / 2, -CW / 2, CL / 2, CW / 2, y0, y0 + 0.007, 0.0015, 0.018),
      slabY(-CL / 2 + 0.008, -CW / 2 + 0.01, CL / 2 - 0.008, CW / 2 - 0.01, y0 - 0.012, y0 + 0.058, 0.012, 0.024, [], 0.014, 6)];
    for (const z of [-NZ, NZ]) alu.push(slabY(-CL / 2 + 0.03, z - 0.006, CL / 2 - 0.03, z + 0.006, y0 + 0.05, y0 + 0.062, 0.0035, 0.006));
    for (const x of [XF + 0.07, 0, XR - 0.07]) for (const z of [-NZ, NZ]) alu.push(latheY([[0.0001, y0 + 0.05], [0.0125, y0 + 0.05], [0.0105, y0 + 0.064], [0.0001, y0 + 0.064]], 24).translate(x, 0, z));
    // stiffening ribs down the sides
    for (let k = 0; k < 7; k++) for (const s of [-1, 1]) {
      const x = -CL / 2 + 0.04 + k * (CL - 0.08) / 6, z0 = s > 0 ? CW / 2 - 0.0125 : -CW / 2 + 0.0075;
      alu.push(slabY(x - 0.003, z0, x + 0.003, z0 + 0.005, y0 + 0.006, y0 + 0.04, 0.002));
    }
    alu.push(latheY([[0.0001, y0 + 0.04], [0.03, y0 + 0.04], [0.03, y0 + 0.056], [0.027, y0 + 0.062], [0.0001, y0 + 0.062]], 32).translate(0.06, 0, 0));
    const breather = merge(latheY([[0.0001, 0], [0.023, 0], [0.023, 0.005], [0.02, 0.014], [0.012, 0.02], [0.0001, 0.021]], 32).translate(XR - 0.05, y0 + 0.056, 0),
      cylZ(0.0065, 0.04, -0.06, XR - 0.05, y0 + 0.066, 18), torusX(0.0072, 0.0018, 0, 0, 0).rotateY(Math.PI / 2).translate(XR - 0.05, y0 + 0.066, -0.052));
    const camCover = add('cam_cover', 'Cam cover', group([merge(alu), M.aluCast], [breather, M.plastic]), { parent: head });
    const capG = [latheY([[0.0001, 0], [0.0235, 0], [0.025, 0.003], [0.025, 0.012], [0.0225, 0.0165], [0.0001, 0.0165]], 32)];
    for (let k = 0; k < 12; k++) { const a = k / 12 * TAU, g = box(0.004, 0.011, 0.003, 0, 0.007, 0); g.rotateY(a); g.translate(0.025 * Math.cos(a), 0, -0.025 * Math.sin(a)); capG.push(g); }
    capG.push(slabY(-0.017, -0.0035, 0.017, 0.0035, 0.0155, 0.026, 0.0025));
    const fc = add('filler_cap', 'Oil filler cap', mesh(merge(capG), M.plastic), { parent: camCover, pos: [0.06, y0 + 0.062, 0] });
    add('filler_gasket', 'Oil filler cap seal', mesh(torusY(0.0222, 0.0018, 0, 0, 0), M.rubber), { parent: fc, pos: [0.06, y0 + 0.0625, 0] });
    for (const x of [XF + 0.07, 0, XR - 0.07]) for (const z of [-NZ, NZ])
      add('cover_nut', 'Cam cover nut', mesh(merge(nutG(0.008), cylY(0.0085, 0.002, -0.002, 0, 0, 18)), M.zinc), { parent: camCover, pos: [x, y0 + 0.066, z] });
    const outer = xzShape(rrect(LB - 0.012, 0.144, 0.018));
    outer.holes.push(new THREE.Path(rrect(LB - 0.03, 0.126, 0.01).map(([x, z]) => V2(x, -z))));
    add('cover_gasket', 'Cam cover gasket', mesh(extrudeY(outer, 0.004, YH1), M.rubber), { parent: head });
  }

  // ── injectors, clamps, pipes; glow plugs ──
  const injTop = i => new THREE.Vector3(cxi(i), YH1 + 0.006, -0.085), injTip = i => new THREE.Vector3(cxi(i), YH0 + 0.003, -0.012);
  for (let i = 0; i < N; i++) {
    const a = injTip(i), b = injTop(i), len = a.distanceTo(b), dir = b.clone().sub(a).normalize();
    const g = latheY([[0.0001, 0], [0.0028, 0], [0.0045, 0.004], [0.0045, 0.028], [0.0105, 0.03], [0.0105, len - 0.03], [0.0125, len - 0.028],
      [0.0125, len - 0.016], [0.008, len - 0.014], [0.008, len], [0.0001, len]], 24);
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    const spig = cylZ(0.0035, 0.018, -0.026, 0, len - 0.022, 10);
    add('injector', `Injector, ${cylName(i)}`, group([g, M.steel], [spig, M.zinc]), { parent: head, pos: [a.x, a.y, a.z], quat: q, dir: [0, dir.y, dir.z] });
    const cl = add('inj_clamp', `Injector clamp, ${cylName(i)}`, mesh(box(0.034, 0.005, 0.016, 0.012, 0.0025, 0), M.forged), { parent: head, pos: [cxi(i), YH1, -0.081] });
    add('inj_clamp_bolt', `Injector clamp bolt, ${cylName(i)}`, mesh(boltG(0.035, 0.008, 6, true), M.bolt), { parent: cl, pos: [cxi(i) + 0.022, YH1 + 0.005, -0.081] });
  }
  const pumpX0 = XF + 0.004, pumpX1 = XF + 0.175, PZ = -0.145, PY = 0.17;
  // a distributor pump as the catalogue's drawing shows it: its mounting flange, the body, the governor's cover
  // on top with the throttle lever, the distributor head behind with a delivery valve holder for each
  // cylinder and the stop solenoid on it
  const injPump = add('inj_pump', 'Injection pump (distributor type)', group(
    [merge(slabX(pumpX0, pumpX0 + 0.016, PZ - 0.048, PZ + 0.05, PY - 0.06, PY + 0.045, 0.003, 0.016),
      latheX([[0.0001, pumpX0 + 0.012], [0.04, pumpX0 + 0.012], [0.043, pumpX0 + 0.02], [0.043, pumpX1 - 0.058], [0.039, pumpX1 - 0.052], [0.035, pumpX1 - 0.05],
        [0.035, pumpX1 - 0.006], [0.031, pumpX1], [0.0001, pumpX1]], 40).translate(0, PY, PZ),
      slabY(pumpX0 + 0.03, PZ - 0.032, pumpX1 - 0.062, PZ + 0.032, PY + 0.02, PY + 0.062, 0.007, 0.012),
      cylY(0.012, 0.016, PY + 0.022, pumpX1 - 0.028, PZ, 24)), M.aluCast],
    [merge(...Array.from({ length: N }, (_, k) => { const a = k / N * TAU + 0.4; return hexY(0.0068, 0.016).rotateZ(-Math.PI / 2).translate(pumpX1, PY + 0.02 * Math.cos(a), PZ + 0.02 * Math.sin(a)); }),
      cylY(0.0025, 0.012, PY + 0.062, pumpX0 + 0.07, PZ - 0.02, 8), slabY(pumpX0 + 0.06, PZ - 0.075, pumpX0 + 0.08, PZ - 0.012, PY + 0.066, PY + 0.071, 0.002, 0.008),
      cylY(0.006, 0.008, PY + 0.062, pumpX1 - 0.078, PZ + 0.014, 12), hexY(0.0075, 0.006, PY + 0.07).translate(pumpX1 - 0.078, 0, PZ + 0.014)), M.zinc],
    [merge(latheY([[0.0001, 0], [0.0115, 0], [0.0115, 0.02], [0.009, 0.026], [0.0035, 0.028], [0.0035, 0.034], [0.0001, 0.034]], 24).translate(pumpX1 - 0.028, PY + 0.038, PZ)), M.plastic]));
  const pumpGear = add('pump_gear', 'Injection pump sprocket', mesh(sprocketG(0.0645, 38, 0.026, 4), M.steel), { parent: injPump, pos: [XT, PY, PZ] });
  pumpGear.anim = a => camRotate(pumpGear, a);
  for (let i = 0; i < N; i++) {
    const a = (i / N) * TAU + 0.4, s = [pumpX1 + 0.016, PY + 0.02 * Math.cos(a), PZ + 0.02 * Math.sin(a)], top = injTop(i);
    const pts = [s, [pumpX1 + 0.035 + i * 0.006, PY + 0.06 + i * 0.012, PZ - 0.01], [pumpX1 + 0.03, 0.36, -0.16], [top.x, YH1 + 0.04, -0.125], [top.x, top.y + 0.004, -0.098], [top.x, top.y - 0.004, -0.09]];
    add('inj_pipe', `Injector pipe, ${cylName(i)}`, group([tubeG(pts, 0.003, 60, 8), M.steel],
      [merge(cylX(0.006, 0.01, s[0] - 0.005, s[1], s[2], 6), cylZ(0.0058, 0.01, -0.1, top.x, top.y - 0.004, 6)), M.zinc]));
  }
  for (let i = 0; i < N; i++) {
    const x = cxi(i) + 0.022, a = new THREE.Vector3(x, YH0 + 0.004, 0.018), b = new THREE.Vector3(x, YH0 + 0.055, 0.103);
    const len = a.distanceTo(b), dir = b.clone().sub(a).normalize(), q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    const g = latheY([[0.0001, 0], [0.0024, 0], [0.0026, 0.024], [0.0045, 0.026], [0.0045, len - 0.02], [0.0065, len - 0.018], [0.0065, len - 0.008],
      [0.0025, len - 0.006], [0.0025, len + 0.008], [0.0001, len + 0.008]], 18);
    add('glow', `Glow plug, ${cylName(i)}`, mesh(g, M.zinc), { parent: head, pos: [a.x, a.y, a.z], quat: q, dir: [0, dir.y, dir.z] });
  }
  add('glow_bus', 'Glow plug bus bar', mesh(box(cxi(N - 1) - cxi(0) + 0.016, 0.0025, 0.009, (cxi(0) + cxi(N - 1)) / 2 + 0.022, YH0 + 0.063, 0.108), M.copper), { parent: head });

  // ── intake: manifold, EGR valve ──
  {
    const im = [slabX(XF + 0.045, XR - 0.012, -0.181, -0.119, YH0 + 0.014, YH0 + 0.076, 0.01, 0.024),
      latheX([[0.0001, XF + 0.012], [0.024, XF + 0.012], [0.027, XF + 0.016], [0.027, XF + 0.02], [0.024, XF + 0.022], [0.024, XF + 0.05], [0.0001, XF + 0.05]], 32).translate(0, YH0 + 0.045, -0.15)];
    for (let i = 0; i < N - 1; i++) im.push(slabY((cxi(i) + cxi(i + 1)) / 2 - 0.003, -0.176, (cxi(i) + cxi(i + 1)) / 2 + 0.003, -0.124, YH0 + 0.07, YH0 + 0.08, 0.002));
    for (let i = 0; i < N; i++) im.push(tubeG([[cxi(i), YH0 + 0.03, -0.1165], [cxi(i), YH0 + 0.034, -0.13], [cxi(i), YH0 + 0.045, -0.145]], 0.016, 12, 14),
      slabZ(-0.1165, -0.1085, cxi(i) - 0.021, cxi(i) + 0.021, YH0 + 0.01, YH0 + 0.05, 0.0015, 0.008));
    const man = add('intake_manifold', 'Intake manifold', mesh(merge(im), M.aluCast), { parent: head });
    add('egr_valve', 'EGR valve', group([merge(cylX(0.034, 0.05, XR - 0.012, YH0 + 0.045, -0.15, 24), cylY(0.008, 0.03, YH0 + 0.07, XR + 0.013, -0.15)), M.aluCast],
      [latheY([[0.0001, 0.02], [0.03, 0.012], [0.03, 0], [0.0001, 0]], 24).translate(XR + 0.013, YH0 + 0.098, -0.15), M.blackPaint]), { parent: man });
    for (let i = 0; i < N; i++) add('intake_gasket', `Intake manifold gasket, ${cylName(i)}`, mesh(box(0.044, 0.042, 0.0015, cxi(i), YH0 + 0.03, -0.1078), M.fibre), { parent: head });
  }
  // ── exhaust: gaskets, manifold, nuts, turbo ──
  let exh;
  {
    const em = [], coll = [0.0, 0.178, YH0 - 0.003];
    for (let i = 0; i < N; i++) {
      em.push(tubeG([[cxi(i), YH0 + 0.035, 0.1165], [cxi(i), YH0 + 0.032, 0.137], [cxi(i) * 0.55, YH0 + 0.012, 0.165], [coll[0], coll[2], coll[1]]], 0.0165, 30, 14));
      em.push(slabZ(0.1085, 0.1165, cxi(i) - 0.02, cxi(i) + 0.02, YH0 + 0.015, YH0 + 0.055, 0.0015, 0.008));
    }
    em.push(cylY(0.03, 0.04, YH0 - 0.06, 0, 0.178, 24));
    exh = add('exh_manifold', 'Exhaust manifold', mesh(merge(em), M.rusty), { parent: head });
    for (let i = 0; i < N; i++) {
      add('exh_gasket', `Exhaust manifold gasket, ${cylName(i)}`, mesh(box(0.042, 0.042, 0.0015, cxi(i), YH0 + 0.035, 0.1078), M.gasket), { parent: head });
      for (const dx of [-0.016, 0.016]) {
        const g = nutG(0.008); g.rotateX(Math.PI / 2);
        add('exh_nut', `Exhaust manifold nut, ${cylName(i)}`, mesh(merge(g, cylZ(0.004, 0.02, -0.012)), M.zinc), { parent: exh, pos: [cxi(i) + dx, YH0 + 0.035 + (dx > 0 ? -0.013 : 0.013), 0.1165] });
      }
    }
    const tx = 0.0, tz = 0.205, ty = YH0 - 0.1;
    const turbo = [];
    // the turbine: its scroll of hot, rusted iron winding in from the manifold above, the flange it hangs from,
    // its outlet and the outlet's studs
    const tvx = tx - 0.022, cvx = tx + 0.068;
    const on = g => g.translate(0, ty, tz);
    turbo.push([merge(voluteG(tvx, ty, tz, 0.026, 0.036, 0.009, 0.02, Math.PI / 2 - 0.92 * TAU, 0.92),
      on(latheX([[0.0001, tvx - 0.026], [0.022, tvx - 0.026], [0.03, tvx - 0.018], [0.031, tvx + 0.012], [0.024, tvx + 0.02], [0.0001, tvx + 0.02]], 36)),
      on(latheX([[0.019, tvx - 0.04], [0.035, tvx - 0.04], [0.035, tvx - 0.033], [0.024, tvx - 0.033], [0.024, tvx - 0.026], [0.019, tvx - 0.026]], 36)),
      slabY(-0.036, 0.15, 0.03, 0.206, YH0 - 0.066, YH0 - 0.058, 0.002, 0.008)), M.turbine]);
    turbo.push([merge(...[0, 1, 2].map(k => { const a = k / 3 * TAU + 0.5; return hexY(0.0055, 0.006).rotateZ(Math.PI / 2).translate(tvx - 0.04, ty + 0.029 * Math.cos(a), tz + 0.029 * Math.sin(a)); })), M.zinc]);
    // the bearing housing between, its oil feed on top and its drain below
    turbo.push([merge(on(latheX([[0.0001, tvx + 0.02], [0.026, tvx + 0.02], [0.026, tvx + 0.026], [0.018, tvx + 0.031], [0.018, tx + 0.036],
      [0.027, tx + 0.041], [0.027, tx + 0.046], [0.0001, tx + 0.046]], 32)), cylY(0.0055, 0.012, ty + 0.017, tx + 0.016, tz, 12), hexY(0.007, 0.006, ty + 0.027).translate(tx + 0.016, 0, tz)), M.ironDark]);
    // the compressor: its back plate, its aluminium scroll winding out to the outlet, its cover and inlet
    turbo.push([merge(on(latheX([[0.0001, tx + 0.046], [0.05, tx + 0.046], [0.052, tx + 0.05], [0.05, tx + 0.054], [0.0001, tx + 0.054]], 48)),
      voluteG(cvx, ty, tz, 0.034, 0.05, 0.011, 0.025, Math.PI / 2 + 0.92 * TAU, -0.92),
      on(latheX([[0.0001, cvx - 0.012], [0.04, cvx - 0.012], [0.04, cvx + 0.004], [0.033, cvx + 0.016], [0.029, cvx + 0.02], [0.0001, cvx + 0.02]], 40)),
      on(latheX([[0.0245, cvx + 0.02], [0.029, cvx + 0.02], [0.029, tx + 0.118], [0.031, tx + 0.12], [0.031, tx + 0.123], [0.028, tx + 0.125], [0.0245, tx + 0.125]], 40)),
      sweepG([[cvx, ty + 0.05, tz - 0.004], [cvx, ty + 0.056, tz + 0.03], [cvx + 0.004, ty + 0.1, tz + 0.068], [cvx + 0.006, ty + 0.15, tz + 0.1]], [0.025, 0.023, 0.021, 0.02], 20),
      new THREE.TorusGeometry(0.0205, 0.0025, 8, 32).rotateX(Math.PI / 2 + 0.57).translate(cvx + 0.006, ty + 0.142, tz + 0.094)), M.aluCast]);
    // the vane actuator: a vacuum can on a bracket, its rod up to the vanes' lever
    const ax = tx + 0.03, az = tz + 0.058;
    turbo.push([merge(latheY([[0.0001, 0], [0.026, 0], [0.028, 0.004], [0.028, 0.009], [0.026, 0.011], [0.026, 0.014], [0.012, 0.022], [0.0001, 0.022]], 36).translate(ax, ty - 0.078, az),
      cylZ(0.003, 0.016, 0.02, ax + 0.012, ty - 0.07, 8).translate(0, 0, az - 0.02), slabY(ax - 0.008, az - 0.04, ax + 0.008, az - 0.02, ty - 0.058, ty - 0.03, 0.002)), M.blackPaint]);
    turbo.push([merge(cylY(0.0022, 0.075, ty - 0.058, ax, az, 8), box(0.006, 0.004, 0.03, ax, ty + 0.018, az - 0.014)), M.steel]);
    // oil feed from the block, oil drain back to the crankcase
    turbo.push([tubeG([[0.0, YD - 0.03, WB / 2 + 0.005], [0.02, ty + 0.06, tz - 0.04], [tx + 0.016, ty + 0.033, tz]], 0.0035, 30, 8), M.steel]);
    turbo.push([hoseG([[tx + 0.016, ty - 0.02, tz], [tx + 0.016, ty - 0.06, tz - 0.02], [tx + 0.01, 0.045, WB / 2 + 0.035], [tx + 0.004, 0.025, WB / 2 + 0.009]], 0.0065, 30, 12), M.rubber]);
    add('turbo', 'Turbo (variable-vane)', group(...turbo), { parent: exh });
    const hose = add('intake_hose', 'Intake hose', mesh(hoseG([[tx + 0.125, ty, tz], [tx + 0.17, ty + 0.01, tz + 0.01], [tx + 0.21, ty + 0.08, tz + 0.04], [tx + 0.24, ty + 0.16, tz + 0.08]], 0.031, 30, 18), M.rubber));
    add('hose_sleeve', 'Intake hose sleeve', mesh(merge(torusX(0.033, 0.004, tx + 0.13, ty, tz), torusX(0.033, 0.004, tx + 0.145, ty, tz)), M.steel), { parent: hose });
  }

  // ── cooling: water pump, the coolant flange and hoses ──
  add('water_pump', 'Water pump', group([merge(cylX(0.04, 0.012, XF - 0.012, 0.12, 0.07, 28), box(0.02, 0.05, 0.04, XF - 0.006, 0.155, 0.09)), M.aluCast],
    [sprocketG(0.03, 18, 0.024).translate(XT, 0.12, 0.07), M.steel]));
  {
    const fl = add('hose_adapter', 'Coolant flange', mesh(merge(box(0.012, 0.05, 0.05, XR + 0.006, YH0 + 0.05, 0.03), cylX(0.017, 0.03, XR + 0.012, YH0 + 0.06, 0.03, 20), cylX(0.014, 0.025, XR + 0.012, YH0 + 0.035, 0.015, 20)), M.plastic), { parent: head });
    add('coolant_hose', 'Coolant hose, to the radiator (top)', mesh(merge(hoseG([[XR + 0.035, YH0 + 0.06, 0.03], [XR + 0.08, YH0 + 0.06, 0.05], [XR + 0.11, YH0 + 0.02, 0.16], [XR + 0.12, YH0 - 0.04, 0.26]], 0.018, 30, 14),
      torusX(0.019, 0.003, XR + 0.04, YH0 + 0.06, 0.03)), M.rubber), { parent: fl });
    add('coolant_hose', 'Coolant hose, to the heater', mesh(merge(hoseG([[XR + 0.035, YH0 + 0.035, 0.015], [XR + 0.07, YH0 + 0.02, -0.02], [XR + 0.09, YH0 + 0.08, -0.1], [XR + 0.1, YH0 + 0.14, -0.15]], 0.012, 30, 12)), M.rubber), { parent: fl });
  }

  // ── lubrication: oil filter housing, cooler, filter; dipstick ──
  {
    const hx = 0.075, hz = -0.15;
    const hs = add('filter_housing', 'Oil filter housing', mesh(merge(slabY(hx - 0.035, -WB / 2 - 0.05, hx + 0.035, -WB / 2 + 0.002, 0.02, 0.13, 0.004, 0.014),
      latheY([[0.0001, 0], [0.046, 0], [0.047, 0.004], [0.047, 0.016], [0.043, 0.02], [0.0001, 0.02]], 40).translate(hx, 0, hz), slabY(hx - 0.026, -0.155, hx + 0.026, -0.1, 0.012, 0.05, 0.005, 0.012)), M.aluCast));
    add('cooler_gasket', 'Oil cooler gasket', mesh(torusY(0.036, 0.0022, hx, -0.002, hz), M.rubber), { parent: hs });
    const cooler = [];
    for (let k = 0; k < 7; k++) cooler.push(cylY(0.045, 0.0028, -0.034 + k * 0.0045, hx, hz, 30));
    cooler.push(cylY(0.03, 0.034, -0.036, hx, hz, 24));
    const oc = add('oil_cooler', 'Oil cooler', mesh(merge(cooler), M.alu), { parent: hs });
    add('filter_gasket', 'Oil filter seal', mesh(torusY(0.031, 0.0022, hx, -0.0385, hz), M.rubber), { parent: oc });
    add('oil_filter', 'Oil filter', mesh(latheY([[0.0001, -0.142], [0.03, -0.142], [0.038, -0.134], [0.038, -0.045], [0.034, -0.039], [0.0001, -0.039]], 32).translate(hx, 0, hz), M.filter), { parent: oc });
    const dx = -0.088;
    const tube = add('dip_tube', 'Dipstick tube', mesh(tubeG([[dx, YSUMP - 0.04, WB / 2 - 0.004], [dx, YSUMP + 0.01, WB / 2 + 0.012], [dx, 0.2, WB / 2 + 0.014], [dx, 0.38, WB / 2 + 0.035], [dx, 0.45, WB / 2 + 0.04]], 0.005, 40, 8), M.steel));
    add('dip_oring', 'Dipstick tube O-ring', mesh(torusY(0.0062, 0.0015, dx, YSUMP - 0.006, WB / 2 + 0.002), M.rubber), { parent: tube });
    add('dipstick', 'Dipstick', mesh(merge(new THREE.TorusGeometry(0.014, 0.004, 8, 20).translate(dx, 0.468, WB / 2 + 0.04), cylY(0.0055, 0.012, 0.448, dx, WB / 2 + 0.04, 12)), M.yellow), { parent: tube });
  }

  // ── timing belt round the crank, water pump, tensioner, camshaft, injection pump and idler; its covers ──
  const timing = [{ z: 0, y: 0, r: 0.032 }, { z: 0.07, y: 0.12, r: 0.03 }, { z: 0.1, y: 0.28, r: -0.0315 }, { z: ZV, y: YC, r: 0.0645 },
    { z: PZ, y: PY, r: 0.0645 }, { z: -0.12, y: 0.06, r: -0.0295 }];
  add('tbelt', CHAIN ? 'Timing chain' : 'Timing belt', CHAIN ? mesh(chainG(beltPath(timing), XT, 0.0095), M.chain) : mesh(beltG(beltPath(timing), XT, 0.025, 0.0035, 0.0095), M.belt));
  // a roller as the catalogue's pictures show them: a pressed steel shell on its bearing, the bearing's seal
  // showing dark in the middle; the tensioner's eccentric plate with its pointer, and the bolt through it
  const roller = (r, y, z) => [latheX([[0.012, -0.0095], [0.0195, -0.0095], [0.022, -0.013], [r - 0.0008, -0.013], [r, -0.012], [r, 0.012],
    [r - 0.0008, 0.013], [0.012, 0.013], [0.012, -0.0095]], 48).translate(XT, y, z),
    latheX([[0.006, -0.0099], [0.0125, -0.0099], [0.0125, -0.0094], [0.006, -0.0094]], 32).translate(XT, y, z)];
  {
    const [shell, race] = roller(0.0285, 0.28, 0.1);
    const plate = extrudeX(zyShape([...arcPts(0, 0, 0.019, -1.2, Math.PI + 1.2, 20), [0.004, -0.03], [-0.004, -0.03]].map(([z, y]) => [z + 0.1, y + 0.28])), 0.0025, XT - 0.0165, 8);
    add('tensioner', CHAIN ? 'Timing chain tensioner' : 'Timing belt tensioner', group([shell, M.steel], [race, M.rubber],
      [merge(plate, box(0.008, 0.02, 0.05, XF - 0.004, 0.27, 0.085)), M.zinc], [merge(hexY(0.0088, 0.008).rotateZ(Math.PI / 2).translate(XT - 0.0145, 0.28, 0.1), cylX(0.005, 0.03, XT - 0.016, 0.28, 0.1, 10)), M.bolt]));
  }
  {
    const [shell, race] = roller(0.026, 0.06, -0.12);
    add('idler', CHAIN ? 'Timing chain guide' : 'Timing belt idler', group([shell, M.steel], [race, M.rubber],
      [merge(hexY(0.0085, 0.008).rotateZ(Math.PI / 2).translate(XT - 0.0135, 0.06, -0.12), cylX(0.005, 0.03, XT - 0.016, 0.06, -0.12, 10)), M.bolt]));
  }
  {
    // a cover's outline: round every pulley with GROW to spare, cut across at CUT (pushed in by INSET for the rim's inside)
    const cut = 0.2;
    const hull = (grow, keep, inset = 0) => {
      const ring = [];
      for (const p of timing) for (let k = 0; k < 24; k++) { const a = k / 24 * TAU, r = Math.abs(p.r) + grow; ring.push([p.z + r * Math.cos(a), p.y + r * Math.sin(a)]); }
      const edge = keep(cut + 1) ? cut + inset : cut - inset;
      return convexHull([...ring.filter(([, y]) => keep(y) && Math.abs(y - cut) > inset), ...ring.filter(([, y]) => !keep(y)).map(([z]) => [z, edge])]);
    };
    // moulded black plastic: a face with rounded edges, a raised border and stiffening ribs across it
    const span = (poly, y) => {      // where a level line at Y crosses the outline (z from, z to)
      const zs = [];
      for (let i = 0; i < poly.length; i++) {
        const [z1, y1] = poly[i], [z2, y2] = poly[(i + 1) % poly.length];
        if ((y1 - y) * (y2 - y) < 0) zs.push(z1 + (z2 - z1) * (y - y1) / (y2 - y1));
      }
      return zs.length >= 2 ? [Math.min(...zs), Math.max(...zs)] : null;
    };
    const coverG = (keep, holes) => {
      const bv = 0.0018, x0 = XT - 0.027;
      const faceS = zyShape(hull(0.016 - bv, keep), holes.map(h => ({ ...h, r: h.r + bv })));
      const face = new THREE.ExtrudeGeometry(faceS, { depth: 0.005 - 2 * bv, bevelEnabled: true, bevelThickness: bv, bevelSize: bv, bevelSegments: 3, curveSegments: 20 });
      face.rotateY(Math.PI / 2); face.translate(x0 + bv, 0, 0);
      const rim = zyShape(hull(0.016, keep)); rim.holes.push(new THREE.Path(hull(0.012, keep, 0.004).map(([z, y]) => V2(-z, y))));
      const border = zyShape(hull(0.0125, keep, 0.0035)); border.holes.push(new THREE.Path(hull(0.009, keep, 0.0075).map(([z, y]) => V2(-z, y))));
      const out = [face, extrudeX(rim, 0.036, XT - 0.022), extrudeX(border, 0.0025, x0 - 0.0025, 6)];
      const inner = hull(0.004, keep, 0.012);
      const ys = inner.map(([, y]) => y), lo = Math.min(...ys), hi = Math.max(...ys);
      for (let y = lo + 0.018; y < hi - 0.012; y += 0.026) {
        if (holes.length && Math.abs(y) < 0.05) continue;
        const s = span(inner, y);
        if (s && s[1] - s[0] > 0.02) out.push(slabX(x0 - 0.003, x0 + 0.001, s[0], s[1], y - 0.002, y + 0.002, 0.0012));
      }
      return merge(out);
    };
    add('tcover_up', 'Timing belt cover, upper', mesh(coverG(y => y >= cut, []), M.plastic));
    add('tcover_low', 'Timing belt cover, lower', mesh(coverG(y => y <= cut, [{ z: 0, y: 0, r: 0.024 }]), M.plastic));
  }
  // ── accessory belt: the crank pulley, alternator, tensioner ──
  // the damper: a ribbed outer ring on a rubber ring round its hub
  const rubberRing = new THREE.RingGeometry(0.044, 0.05, 64); rubberRing.rotateY(-Math.PI / 2); rubberRing.translate(XA - 0.0131, 0, 0);
  const damperHub = latheX([[0.0001, -0.0145], [0.026, -0.0145], [0.028, -0.0135], [0.028, 0], [0.0001, 0]], 40).translate(XA, 0, 0);
  const damper = add('damper', 'Crank pulley (vibration damper)', group([merge(ribbedG(0.075, 0.026, 6, 0.25).translate(XA, 0, 0), damperHub), M.ironDark], [rubberRing, M.rubber]), { parent: crank });
  damper.anim = crankAnim(damper);
  for (let k = 0; k < 4; k++) {
    const a = k / 4 * TAU + Math.PI / 4, g = boltG(0.03, 0.008, 6, true); g.rotateZ(Math.PI / 2); g.translate(XA - 0.016, 0.032 * Math.cos(a), 0.032 * Math.sin(a));
    const b = add('damper_bolt', 'Crank pulley bolt', mesh(g, M.bolt), { parent: damper }); b.anim = crankAnim(b);
  }
  const AZ = -0.175, AY = 0.0;
  let alt;
  {
    // two cast end shields with cooling slots round them, the stator's laminations between, a plastic cap on
    // the back with the output stud, and the lugs it bolts to the engine by
    const x0 = XA + 0.015, at = g => g.translate(0, AY, AZ);
    const shells = [latheX([[0.016, x0], [0.05, x0], [0.057, x0 + 0.003], [0.059, x0 + 0.008], [0.059, x0 + 0.01], [0.05, x0 + 0.01]], 40),
      latheX([[0.05, x0 + 0.028], [0.059, x0 + 0.028], [0.06, x0 + 0.03], [0.05, x0 + 0.03]], 40),
      latheX([[0.05, x0 + 0.05], [0.06, x0 + 0.05], [0.059, x0 + 0.052], [0.05, x0 + 0.052]], 40),
      latheX([[0.05, x0 + 0.078], [0.058, x0 + 0.078], [0.058, x0 + 0.09], [0.052, x0 + 0.095], [0.02, x0 + 0.095]], 40)];
    for (let k = 0; k < 18; k++) {        // the bars between the slots, front and back
      const a = k / 18 * TAU;
      for (const [xa, xb] of [[x0 + 0.01, x0 + 0.028], [x0 + 0.052, x0 + 0.078]]) {
        const g = box(xb - xa, 0.007, 0.0075); g.translate((xa + xb) / 2, 0.0555, 0); g.rotateX(a); shells.push(g);
      }
    }
    // the lugs: one high, one low, each with its bolt's hole, reaching for the engine
    for (const [ly, lz] of [[0.048, 0.04], [-0.045, 0.046]]) for (const xl of [x0 + 0.004, x0 + 0.082]) {
      shells.push(extrudeX(zyShape(rrect(0.05, 0.024, 0.01).map(([a, b]) => [a + lz, b + ly]), [{ z: lz + 0.014, y: ly, r: 0.0055 }]), 0.011, xl, 12));
    }
    const core = merge(cylX(0.05, 0.094, x0 + 0.001, 0, 0, 36), ...Array.from({ length: 6 }, (_, k) => torusX(0.0595, 0.0012, x0 + 0.032 + k * 0.0032, 0, 0)));
    const cap = merge(latheX([[0.0001, x0 + 0.095], [0.044, x0 + 0.095], [0.046, x0 + 0.1], [0.04, x0 + 0.112], [0.0001, x0 + 0.114]], 32),
      cylX(0.0045, 0.012, x0 + 0.112, 0.018, -0.01, 10));
    alt = add('alternator', 'Alternator', group([at(merge(shells)), M.aluCast], [at(core), M.ironDark], [at(cap), M.plastic]));
  }
  const altP = add('alt_pulley', 'Alternator pulley', mesh(ribbedG(0.028, 0.026, 6, 0.3).translate(XA, AY, AZ), M.steel), { parent: alt });
  altP.anim = a => { altP.obj.rotation.x = a * 2.7; };
  const accTen = { z: -0.09, y: 0.079, r: -0.0265 };
  add('acc_tensioner', 'Accessory belt tensioner', mesh(merge(latheX([[0.006, -0.013], [0.022, -0.013], [0.022, 0.013], [0.006, 0.013]], 30).translate(XA, accTen.y, accTen.z), box(0.01, 0.075, 0.016, XA + 0.016, accTen.y - 0.03, accTen.z)), M.forged));
  add('ribbed', 'Accessory belt (ribbed)', mesh(beltG(beltPath([{ z: 0, y: 0, r: 0.077 }, { ...accTen, r: -0.0265 }, { z: AZ, y: AY, r: 0.0295 }]), XA, 0.022, 0.0035, 0, 6), M.belt));
}

const ENGINE = {
  groups: ['Belts and timing', 'Cylinder head', 'Valvetrain', 'Fuel and glow plugs', 'Air, turbo and exhaust',
    'Block and bottom end', 'Pistons and rods', 'Lubrication', 'Cooling', 'Accessories'],
  openGroups: ['Valvetrain', 'Cylinder head'],
  cat: CAT,
  fixed: ['block'],
  ao: 0.045,
  floorY: null,
  views: { front: ['Belt end', [-1, 0.35, 0.25]], intake: ['Intake side', [-0.25, 0.4, -1]], exhaust: ['Exhaust side', [0.3, 0.45, 1]],
    top: ['Top', [-0.05, 1, 0.12]], under: ['Underneath', [-0.2, -0.9, 0.35]] },
  firstDir: [-0.85, 0.55, 0.75],
  build,
  steps: () => [
    ['The accessory belt', ['ribbed']], ['The alternator and its pulley; the belt tensioner', ['alt_pulley', 'alternator', 'acc_tensioner']],
    ['The timing covers', ['tcover_up', 'tcover_low']], ['The crank pulley and its bolts', ['damper_bolt', 'damper']],
    [`The timing ${CHAIN ? 'chain' : 'belt'}`, ['tbelt']], ['The tensioner and the idler', ['tensioner', 'idler']],
    ['The camshaft sprocket', ['cam_bolt', 'cam_gear']], ['The injection pump sprocket', ['pump_gear']],
    ['The injector pipes', ['inj_pipe']], ['The intake hose', ['hose_sleeve', 'intake_hose']], ['The turbo', ['turbo']],
    ['The exhaust manifold: its nuts, the manifold, its gaskets', ['exh_nut', 'exh_manifold', 'exh_gasket']],
    ['The intake manifold and the EGR valve; their gaskets', ['egr_valve', 'intake_manifold', 'intake_gasket']],
    ['The cam cover: its nuts, the filler cap, the cover and its gasket', ['cover_nut', 'filler_gasket', 'filler_cap', 'cam_cover', 'cover_gasket']],
    ['The injectors: clamps and injectors', ['inj_clamp_bolt', 'inj_clamp', 'injector']], ['The glow plugs and their bus bar', ['glow_bus', 'glow']],
    ['The coolant hoses and flange', ['coolant_hose', 'hose_adapter']], ['The cylinder head bolts', ['head_bolt']],
    ['The cylinder head', ['head']], ['The head gasket', ['head_gasket']],
    ['On the bench: the camshaft caps and the camshaft, its seal', ['cap_nut', 'cam_cap', 'cam_seal', 'cam']],
    ['The cam followers', ['follower']], ['The valves: keepers, spring caps, springs, stem seals, valves', ['keeper', 'retainer', 'spring', 'stem_seal', 'valve_in', 'valve_ex']],
    ['The sump: its bolts and drain plug, the sump, its gasket', ['drain_plug', 'sump_bolt', 'sump', 'sump_gasket']],
    ['The oil pump, its chain and tensioner', ['chain_tens', 'oil_chain', 'oil_pump']],
    ['The big-end caps: bolts, caps, lower shells', ['rod_bolt', 'rod_cap']],
    ['The pistons and rods, out through the top', ['piston']],
    ['Each piston off its rod: rings, circlips, pins', ['ring', 'circlip', 'gpin', 'rod']],
    ['The flywheel and its bolts', ['fly_bolt', 'flywheel']],
    ['The oil filter, cooler and housing', ['oil_filter', 'filter_gasket', 'oil_cooler', 'cooler_gasket', 'filter_housing']],
    ['The dipstick and its tube', ['dipstick', 'dip_tube', 'dip_oring']], ['The water pump', ['water_pump']], ['The injection pump', ['inj_pump']],
    ['The crankshaft oil seals', ['crank_seal']], ['The main bearing caps: bolts, caps, lower shells, thrust washers', ['main_bolt', 'main_cap', 'thrust']],
    ['The crankshaft and its sprocket', ['crank_gear', 'crank']], ['The upper main shells, from the block', ['main_shell', 'rod_shell']],
  ],
  words(c) {
    const base = { thing: 'engine', bare: 'Stripped to the bare block', unlisted: 'Not in your catalogue’s list for this engine: drawn so the engine is whole.',
      intro: 'Tap any part of the engine, or a part’s name below. It comes off and goes back on.', about: 'About this engine',
      elsewhere: 'In your catalogue for this engine, but not on the engine itself', stage: 'The engine' };
    if (!c) return base;
    const yearNote = CFG.year && CFG.asked_year && String(CFG.year) !== String(CFG.asked_year) ? ` (your catalogue lists it to ${CFG.year}; you asked for ${CFG.asked_year})` : CFG.year ? ` (${CFG.year})` : '';
    return { ...base, title: `${CFG.make} ${D.name}`, kicker: `From your parts catalogue: ${CFG.make} ${CFG.model}${yearNote}`,
      lede: `${CFG.words[0].toUpperCase()}${CFG.words.slice(1)}${CFG.built_words && !D.known ? ', ' + CFG.built_words : ''}. ${c.pieceCount} pieces of ${c.kinds} kinds, each its own part: tap one to take it off and put it back, or strip it down in workshop order. ${c.catRows.length} of your catalogue’s parts for it are listed.`,
      facts: D.facts,
      honest: (D.known ? 'Drawn to those published figures.' : 'Drawn from its size.') +
        ' The castings (block, head, manifolds, housings) are drawn by the machine to fit them, not scanned from this engine. The belt rollers, the camshaft sprocket, the alternator, the injection pump and the filler cap are shaped after your catalogue’s own pictures of them. Parts your catalogue lists for this engine carry its OEM numbers; the others are drawn so the engine is whole, and say so.' };
  },
};

import * as THREE from 'three';

/**
 * A constructed, serviceable front brake corner for the training vehicle.
 * Dimensions follow the measured source disc, not an OEM engineering drawing.
 * X is the axle, Y is up, +Z is the nose; side=1 is the left/outboard +X face.
 * Return groups separately so removing a caliper never removes the hub or hose.
 */
export function buildFrontBrake({
  side = 1, discRadius = .1708, discThickness = .0309, materialFactory,
} = {}) {
  if (![1, -1].includes(side)) throw new RangeError('Brake side must be 1 or -1');
  if (!(discRadius > 0 && discThickness > 0 && discThickness < discRadius / 2)) {
    throw new RangeError('Brake disc dimensions must be positive and physically plausible');
  }
  const mat = (color, options, finish = 'cast') => materialFactory
    ? materialFactory(color, options, finish)
    : new THREE.MeshPhysicalMaterial({ color, ...options });
  const iron = mat(0x9da2a4, { metalness: .9, roughness: .32 }, 'brushed');
  const cutEdge = mat(0x737a7d, { metalness: .75, roughness: .49 });
  const hatMetal = mat(0x646a6d, { metalness: .78, roughness: .47 });
  const wear = mat(0xb0b4b6, { metalness: .88, roughness: .4 }, 'brushed');
  const oxide = mat(0x584d42, { metalness: .36, roughness: .87 });
  const caliperPaint = mat(0xad171e, {
    metalness: .32, roughness: .56, clearcoat: .15, clearcoatRoughness: .5,
  }, 'paint');
  const castSteel = mat(0x62696c, { metalness: .69, roughness: .56 });
  const pinSteel = mat(0xc0c5c7, { metalness: .95, roughness: .22 }, 'brushed');
  const zinc = mat(0x969d9d, { metalness: .85, roughness: .35 }, 'brushed');
  const rubber = mat(0x202328, { metalness: .03, roughness: .84 }, 'rubber');
  const cavity = mat(0x202125, { metalness: .22, roughness: .87 });
  const lining = mat(0x47423e, { metalness: .08, roughness: .94 });
  const strutPaint = mat(0x24292c, { metalness: .64, roughness: .5 });
  const springPaint = mat(0x141a1f, { metalness: .62, roughness: .32 });
  const weatheredCast = mat(0x6d695f, { metalness: .43, roughness: .81 });
  const groups = {};
  for (const name of ['rotor', 'caliper', 'hub', 'knuckle', 'extras', 'pads']) {
    const group = new THREE.Group();
    group.name = `front-brake-${name}-${side === 1 ? 'left' : 'right'}`;
    group.userData.constructedTrainingGeometry = true;
    group.userData.component = name;
    groups[name] = group;
  }
  const { rotor, caliper, hub, knuckle, extras, pads } = groups;
  const geometryCache = new Map();
  function mesh(parent, geometry, material, name, x = 0, y = 0, z = 0) {
    const object = new THREE.Mesh(geometry, material);
    object.name = name;
    object.position.set(side * x, y, z);
    object.castShadow = true;
    object.receiveShadow = true;
    parent.add(object);
    return object;
  }
  // Shape coordinates are (z,y), with depth running along +outboard X.
  function profile(parent, shape, x, depth, material, name, bevel = .0015) {
    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: Math.max(.00001, depth - 2 * bevel), curveSegments: 7,
      bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel,
      bevelSegments: 2,
    });
    geometry.translate(0, 0, bevel);
    // rotateY maps old +X to -Z; mirror the 2D shape before rotation.
    geometry.rotateY(-Math.PI / 2);
    geometry.scale(-side, 1, 1);
    if (side === 1) {
      // A single reflection reverses winding. Swap every triangle to preserve
      // front-face culling as well as the generated normals.
      const position = geometry.getAttribute('position');
      const normal = geometry.getAttribute('normal');
      const uv = geometry.getAttribute('uv');
      for (let i = 0; i < position.count; i += 3) {
        for (const attribute of [position, normal, uv]) {
          if (!attribute) continue;
          for (let k = 0; k < attribute.itemSize; k++) {
            const a = (i + 1) * attribute.itemSize + k;
            const b = (i + 2) * attribute.itemSize + k;
            const temp = attribute.array[a];
            attribute.array[a] = attribute.array[b];
            attribute.array[b] = temp;
          }
        }
      }
    }
    geometry.computeVertexNormals();
    return mesh(parent, geometry, material, name, x);
  }
  function roundProfile(z0, y0, width, height, radius) {
    const s = new THREE.Shape();
    const r = Math.min(radius, width / 2, height / 2);
    s.moveTo(z0 + r, y0); s.lineTo(z0 + width - r, y0);
    s.quadraticCurveTo(z0 + width, y0, z0 + width, y0 + r);
    s.lineTo(z0 + width, y0 + height - r);
    s.quadraticCurveTo(z0 + width, y0 + height, z0 + width - r, y0 + height);
    s.lineTo(z0 + r, y0 + height);
    s.quadraticCurveTo(z0, y0 + height, z0, y0 + height - r);
    s.lineTo(z0, y0 + r); s.quadraticCurveTo(z0, y0, z0 + r, y0);
    return s;
  }
  function axial(parent, radius, length, material, name, x, y = 0, z = 0, segments = 32) {
    const key = `${radius}/${length}/${segments}`;
    if (!geometryCache.has(key)) {
      const geometry = new THREE.CylinderGeometry(radius, radius, length, segments);
      geometry.rotateZ(Math.PI / 2);
      geometryCache.set(key, geometry);
    }
    return mesh(parent, geometryCache.get(key), material, name, x, y, z);
  }
  function ring(parent, radius, tube, material, name, x, y = 0, z = 0, segments = 48, radialSegments = 4) {
    const geometry = new THREE.TorusGeometry(radius, tube, radialSegments, segments);
    geometry.rotateY(Math.PI / 2);
    return mesh(parent, geometry, material, name, x, y, z);
  }
  function lathe(parent, points, material, name, segments = 80) {
    const geometry = new THREE.LatheGeometry(points.map(([r, x]) => new THREE.Vector2(r, x)), segments);
    geometry.rotateZ(-side * Math.PI / 2);
    return mesh(parent, geometry, material, name);
  }
  function annulus(parent, inner, outer, fromX, depth, material, name, boltHoles = false) {
    if (!boltHoles) return lathe(parent, [[inner, fromX], [outer, fromX],
      [outer, fromX + depth], [inner, fromX + depth], [inner, fromX]], material, name, 96);
    const s = new THREE.Shape();
    const circle = (path, radius, count, clockwise, z = 0, y = 0) => {
      for (let i = 0; i <= count; i++) {
        const a = i / count * Math.PI * 2 * (clockwise ? -1 : 1);
        const x = z + radius * Math.cos(a), py = y + radius * Math.sin(a);
        if (!i) path.moveTo(x, py); else path.lineTo(x, py);
      }
    };
    circle(s, outer, 64, false);
    const bore = new THREE.Path();
    circle(bore, inner, 48, true); s.holes.push(bore);
    if (boltHoles) for (let n = 0; n < 5; n++) {
      const a = n * Math.PI * 2 / 5 + Math.PI / 2;
      const hole = new THREE.Path();
      circle(hole, .0074, 18, true, .056 * Math.cos(a), .056 * Math.sin(a));
      s.holes.push(hole);
    }
    return profile(parent, s, fromX, depth, material, name, .00025);
  }
  function tube(parent, points, radius, material, name, segments = 28) {
    const curve = new THREE.CatmullRomCurve3(points.map(([x, y, z]) => new THREE.Vector3(side * x, y, z)));
    return mesh(parent, new THREE.TubeGeometry(curve, segments, radius, 7, false), material, name);
  }

  // Two real friction rings surround an open, internally vented air channel.
  const face = .006, half = discThickness / 2, inner = discRadius * .56;
  annulus(rotor, inner, discRadius, half - face, face, iron, 'outboard-friction-ring');
  annulus(rotor, inner, discRadius, -half, face, iron, 'inboard-friction-ring');
  const vaneShape = new THREE.Shape();
  vaneShape.moveTo(inner - .003, -.0017);
  vaneShape.quadraticCurveTo(.131, .001, discRadius - .0025, .011);
  vaneShape.lineTo(discRadius - .0025, .0144);
  vaneShape.quadraticCurveTo(.129, .0044, inner - .003, .0017);
  vaneShape.closePath();
  const vane = profile(rotor, vaneShape, -half + face, discThickness - 2 * face,
    cutEdge, 'vent-vane-01', .00025);
  for (let n = 1; n < 36; n++) {
    const copy = vane.clone(); copy.name = `vent-vane-${String(n + 1).padStart(2, '0')}`;
    copy.rotation.x = n * Math.PI * 2 / 36; rotor.add(copy);
  }
  // The hat steps inwards to the disc centre; its visible face contains actual
  // holes on a representative five-by-112 mm wheel-bolt circle.
  lathe(rotor, [[inner, .007], [.078, .028], [.075, .030], [.075, .024], [inner, .002]],
    hatMetal, 'disc-hat-sloping-web');
  annulus(rotor, .0315, .078, .024, .006, hatMetal, 'disc-hat-five-bolt-face', true);
  annulus(rotor, discRadius - .0018, discRadius, half + .00015, .00045, oxide, 'outer-wear-lip');
  annulus(rotor, inner, inner + .0022, half + .00012, .0004, oxide, 'inner-wear-lip');
  for (let n = 0; n < 8; n++) {
    const r = inner + .006 + n * (discRadius - inner - .013) / 7;
    ring(rotor, r, .00011, n % 3 ? wear : cutEdge, `outboard-machining-line-${n}`, half + .00012, 0, 0, 32, 3);
    ring(rotor, r, .00009, wear, `inboard-machining-line-${n}`, -half - .0001, 0, 0, 32, 3);
  }
  // A small countersunk locating screw is separate from the five wheel holes.
  axial(rotor, .0035, .0008, zinc, 'disc-locating-screw', .0306, -.037, .014, 16);
  const screwSlot = new THREE.Shape();
  screwSlot.moveTo(.0115, -.0375); screwSlot.lineTo(.0165, -.0375);
  screwSlot.lineTo(.0165, -.0365); screwSlot.lineTo(.0115, -.0365); screwSlot.closePath();
  profile(rotor, screwSlot, .0311, .0002, cavity, 'disc-screw-recess', 0);

  annulus(hub, .019, .0725, .007, .014, castSteel, 'wheel-hub-flange', true);
  lathe(hub, [[.019, -.076], [.038, -.076], [.043, -.064], [.043, -.020], [.038, -.007], [.019, -.007]],
    hatMetal, 'hub-bearing-casing', 48);
  lathe(hub, [[.019, .016], [.032, .016], [.032, .036], [.0305, .038], [.019, .038]],
    zinc, 'hub-centering-spigot', 64);
  axial(hub, .019, .011, cavity, 'axle-recess', .025);
  axial(hub, .0125, .007, zinc, 'axle-bolt', .034, 0, 0, 6);
  axial(hub, .0052, .0007, cavity, 'axle-bolt-hex-socket', .038, 0, 0, 6);
  for (let n = 0; n < 5; n++) {
    const a = n * Math.PI * 2 / 5 + Math.PI / 2;
    const y = .056 * Math.sin(a), z = .056 * Math.cos(a);
    axial(hub, .0068, .002, cavity, `wheel-bolt-bore-${n + 1}`, .006, y, z, 20);
    ring(hub, .0064, .00045, zinc, `bolt-thread-mouth-${n + 1}`, .0207, y, z, 20);
    for (let t = 0; t < 3; t++) {
      ring(hub, .006, .00032, cutEdge, `bolt-thread-${n + 1}-${t}`, .016 - t * .0023, y, z, 16);
    }
  }

  // The cast outer body is a convex, variable-thickness shell around a small
  // oblong inspection opening. Radial surface bands put geometry into the
  // shoulders themselves, so highlights roll across it instead of exposing
  // the completely planar cap produced by a simple shape extrusion.
  const shellPositions = [], shellUvs = [], shellIndices = [];
  const around = 72, bands = 7, shellStride = bands + 1;
  for (let face = 0; face < 2; face++) for (let n = 0; n <= around; n++) {
    const angle = n / around * Math.PI * 2, sy = Math.sin(angle), sz = Math.cos(angle);
    const outsideY = .001 + .084 * sy;
    const outsideZ = .148 + (.038 + .004 * sz + .002 * sy) * sz;
    // Superellipse yields a natural capsule slot with rounded shoulders.
    const insideY = .025 * Math.sign(sy) * Math.pow(Math.abs(sy), .78);
    const insideZ = .151 + .0105 * Math.sign(sz) * Math.pow(Math.abs(sz), .78);
    for (let band = 0; band <= bands; band++) {
      const t = band / bands;
      const y = THREE.MathUtils.lerp(insideY, outsideY, t);
      const z = THREE.MathUtils.lerp(insideZ, outsideZ, t);
      const shoulder = Math.pow(Math.abs(sy), 1.5);
      const roundedThickness = Math.pow(Math.sin(Math.PI * t), .72);
      const x = face === 0
        ? .047 + .009 * roundedThickness + .007 * shoulder + .002 * sz
        : .033 + .003 * shoulder;
      shellPositions.push(side * x, y, z);
      shellUvs.push(n / around, t);
    }
  }
  const shellFaceSize = (around + 1) * shellStride;
  const triangle = (a, b, c) => shellIndices.push(...(side > 0 ? [a, b, c] : [a, c, b]));
  for (let n = 0; n < around; n++) {
    for (let band = 0; band < bands; band++) {
      const a = n * shellStride + band, b = a + shellStride;
      triangle(a, b, a + 1); triangle(b, b + 1, a + 1);
      triangle(a + shellFaceSize, a + 1 + shellFaceSize, b + shellFaceSize);
      triangle(b + shellFaceSize, a + 1 + shellFaceSize, b + 1 + shellFaceSize);
    }
    for (const edge of [0, bands]) {
      const a = n * shellStride + edge, b = a + shellStride;
      if (edge === 0) {
        triangle(a, a + shellFaceSize, b); triangle(b, a + shellFaceSize, b + shellFaceSize);
      } else {
        triangle(a, b, a + shellFaceSize); triangle(b, b + shellFaceSize, a + shellFaceSize);
      }
    }
  }
  const shellGeometry = new THREE.BufferGeometry();
  shellGeometry.setAttribute('position', new THREE.Float32BufferAttribute(shellPositions, 3));
  shellGeometry.setAttribute('uv', new THREE.Float32BufferAttribute(shellUvs, 2));
  shellGeometry.setIndex(shellIndices); shellGeometry.computeVertexNormals();
  mesh(caliper, shellGeometry, caliperPaint, 'caliper-outer-window-casting');
  for (const y of [-.054, .037]) {
    profile(caliper, roundProfile(.119, y, .043, .017, .006), .0305, .016,
      caliperPaint, `caliper-pressure-finger-${y}`, .0015);
  }
  // Broad, rounded cast arches climb over the rotor and flow into the piston
  // housing. Their centreline bends in three dimensions instead of a flat
  // ninety-degree slab connecting the two sides of the caliper.
  for (const sign of [-1, 1]) {
    const path = new THREE.CatmullRomCurve3([
      [-.066, sign * .026, .147], [-.050, sign * .049, .170],
      [-.012, sign * .060, .180], [.021, sign * .063, .176],
      [.048, sign * .058, .162], [.056, sign * .048, .146],
    ].map(([x, y, z]) => new THREE.Vector3(side * x, y, z)));
    const arch = new THREE.TubeGeometry(path, 24, .0145, 12, false);
    mesh(caliper, arch, caliperPaint, `caliper-bridge-${sign < 0 ? 'lower' : 'upper'}`);
    const shoulder = new THREE.SphereGeometry(1, 20, 12);
    shoulder.scale(.021, .023, .025);
    mesh(caliper, shoulder, caliperPaint, `cast-shoulder-${sign}`, .049, sign * .051, .151);
    tube(caliper, [[.060, sign * .033, .166], [.064, sign * .044, .164],
      [.062, sign * .058, .151], [.053, sign * .069, .139]], .0031,
      caliperPaint, `outer-casting-relief-rib-${sign}`, 14);
  }
  // Single piston on the inboard side, with a separate steel piston and a
  // corrugated rubber dust boot. Its axis follows the wheel axle.
  const pistonHousing = lathe(caliper, [[0, -.084], [.023, -.084], [.033, -.079],
    [.039, -.069], [.040, -.050], [.037, -.041], [.033, -.037],
    [.030, -.040], [.030, -.068], [0, -.076]], caliperPaint, 'piston-cast-housing', 40);
  pistonHousing.position.z = .138;
  axial(caliper, .034, .0045, rubber, 'piston-dust-boot-base', -.039, 0, .138, 36);
  axial(caliper, .030, .018, pinSteel, 'brake-piston', -.040, 0, .138, 40);
  for (let n = 0; n < 3; n++) ring(caliper, .031 + n * .0012, .0011,
    rubber, `piston-dust-boot-fold-${n}`, -.038 + n * .0018, 0, .138, 36);
  // Circumferential stiffness ribs blend into the round cylinder.
  for (const sign of [-1, 1]) {
    tube(caliper, [[-.081, sign * .021, .145], [-.074, sign * .030, .153],
      [-.056, sign * .037, .156], [-.044, sign * .034, .153]], .0033,
      caliperPaint, `piston-housing-rib-${sign}`, 12);
  }

  // Carrier follows the inner disc edge and holds the two replaceable pads.
  const carrier = new THREE.Shape();
  carrier.moveTo(.096, -.079); carrier.lineTo(.130, -.082);
  carrier.quadraticCurveTo(.148, -.066, .123, -.055); carrier.lineTo(.110, -.052);
  carrier.lineTo(.110, .052); carrier.lineTo(.123, .055);
  carrier.quadraticCurveTo(.148, .066, .130, .082); carrier.lineTo(.096, .079);
  carrier.quadraticCurveTo(.087, .055, .091, .034); carrier.lineTo(.091, -.034);
  carrier.quadraticCurveTo(.087, -.055, .096, -.079);
  profile(extras, carrier, -.047, .023, castSteel, 'caliper-carrier', .002);
  for (const y of [-.070, .070]) {
    axial(extras, .013, .021, castSteel, `carrier-mount-lug-${y}`, -.055, y, .101, 24);
    axial(extras, .008, .0065, zinc, `carrier-mount-bolt-${y}`, -.072, y, .101, 6);
    axial(caliper, .010, .023, caliperPaint, `guide-pin-boss-${y}`, -.052, y, .154, 24);
    const guideTransition = new THREE.SphereGeometry(1, 16, 10);
    guideTransition.scale(.016, .017, .019);
    mesh(caliper, guideTransition, caliperPaint, `guide-pin-cast-transition-${y}`, -.049, y * .83, .157);
    axial(caliper, .0047, .038, pinSteel, `slide-guide-pin-${y}`, -.032, y, .154, 20);
    for (let n = 0; n < 5; n++) ring(caliper, .0068, .0013, rubber,
      `guide-pin-bellows-${y}-${n}`, -.042 + n * .003, y, .154, 16);
    axial(caliper, .008, .006, zinc, `guide-pin-bolt-${y}`, -.070, y, .154, 6);
    axial(caliper, .0083, .004, rubber, `guide-pin-cap-${y}`, -.075, y, .154, 20);
  }
  // A bent retaining spring sits proud of the cast outer face.
  tube(caliper, [[.070, -.061, .128], [.077, -.046, .130], [.077, -.025, .131],
    [.074, 0, .128], [.077, .025, .131], [.077, .046, .130], [.070, .061, .128]],
    .0016, zinc, 'external-pad-retaining-spring', 32);
  for (const y of [-.061, .061]) axial(caliper, .0038, .002, zinc,
    `spring-anchor-${y}`, .070, y, .128, 16);
  // Bleeder has a hex base, stem and protective cap at the top of the piston.
  axial(caliper, .0057, .006, zinc, 'bleed-screw-hex', -.080, .029, .151, 6);
  axial(caliper, .0028, .012, zinc, 'bleed-screw-neck', -.088, .029, .151, 12);
  axial(caliper, .0047, .007, rubber, 'bleed-screw-dust-cap', -.096, .029, .151, 16);
  tube(caliper, [[-.098, .028, .151], [-.100, .037, .149], [-.085, .037, .143]],
    .0008, rubber, 'bleeder-cap-tether', 12);

  // Two pads can be detached independently by the caller. Their shape is a
  // curved sector matching the swept ring; the shell window shows the back.
  for (const outboard of [false, true]) {
    const pad = new THREE.Group(); pad.name = outboard ? 'outboard-pad' : 'inboard-pad'; pads.add(pad);
    const a = .47;
    const sector = (start, end) => {
      const shape = new THREE.Shape();
      shape.absarc(0, 0, discRadius - .006, start, end, false);
      shape.absarc(0, 0, inner + .007, end, start, true); shape.closePath();
      return shape;
    };
    const padShape = sector(-a, a);
    const offset = outboard ? half + .0007 : -half - .0107;
    // A real gap separates the friction shoulders down to the backing plate.
    profile(pad, sector(-a, -.007), offset, .010, lining, `${pad.name}-friction-lower`, .0005);
    profile(pad, sector(.007, a), offset, .010, lining, `${pad.name}-friction-upper`, .0005);
    profile(pad, padShape, outboard ? offset + .010 : offset - .004, .004,
      castSteel, `${pad.name}-backing`, .0007);
  }

  const knuckleBody = new THREE.Shape();
  knuckleBody.moveTo(-.036, -.110); knuckleBody.quadraticCurveTo(-.053, -.046, -.043, -.022);
  knuckleBody.quadraticCurveTo(-.072, .012, -.045, .059);
  knuckleBody.lineTo(-.037, .128); knuckleBody.quadraticCurveTo(-.008, .145, .020, .128);
  knuckleBody.lineTo(.026, .069); knuckleBody.quadraticCurveTo(.068, .044, .063, .003);
  knuckleBody.quadraticCurveTo(.065, -.043, .017, -.061);
  knuckleBody.lineTo(.012, -.115); knuckleBody.closePath();
  profile(knuckle, knuckleBody, -.123, .045, weatheredCast, 'steering-knuckle-casting', .004);
  lathe(knuckle, [[.031, -.124], [.056, -.124], [.057, -.086], [.045, -.071], [.031, -.071]],
    weatheredCast, 'knuckle-bearing-boss', 40);
  // Strut pinch collar and bolt are visible behind the upper casting.
  const collar = new THREE.Mesh(new THREE.CylinderGeometry(.033, .034, .070, 28), weatheredCast);
  collar.name = 'strut-pinch-collar'; collar.position.set(-side * .109, .130, -.014);
  collar.castShadow = collar.receiveShadow = true; knuckle.add(collar);
  axial(knuckle, .0065, .060, zinc, 'strut-pinch-bolt', -.108, .106, .025, 6);
  const joint = new THREE.Mesh(new THREE.SphereGeometry(.021, 18, 12), rubber);
  joint.name = 'lower-ball-joint-boot'; joint.scale.set(1, .68, 1);
  joint.position.set(-side * .103, -.123, -.010); knuckle.add(joint);

  // A complete MacPherson leg stays attached to the exposed wheel corner.
  // Its axis leans towards the body as it climbs from the pinch collar to the
  // top mount; a half-metre floating upright or unsupported coil is avoided.
  const strut = new THREE.Group();
  strut.name = 'macpherson-strut';
  strut.userData.component = 'suspension-strut';
  strut.position.set(-side * .109, .115, -.014);
  const strutDirection = new THREE.Vector3(-side * .055, .48, -.024).normalize();
  strut.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), strutDirection);
  extras.add(strut);
  const uprightLathe = (points, material, name, segments = 32) => {
    const geometry = new THREE.LatheGeometry(points.map(([r, y]) => new THREE.Vector2(r, y)), segments);
    return mesh(strut, geometry, material, name);
  };
  const uprightCylinder = (radius, length, y, material, name, segments = 28) =>
    mesh(strut, new THREE.CylinderGeometry(radius, radius, length, segments), material, name, 0, y);
  uprightLathe([[0, -.025], [.024, -.025], [.027, -.014], [.027, .203],
    [.029, .209], [.029, .223], [.023, .227], [.011, .227]],
    strutPaint, 'strut-damper-body');
  uprightCylinder(.011, .214, .328, pinSteel, 'strut-chrome-piston-rod');
  uprightLathe([[.012, .218], [.028, .218], [.030, .224], [.030, .231],
    [.013, .232]], zinc, 'damper-seal-retainer');
  uprightLathe([[.011, .228], [.027, .228], [.027, .237], [.012, .239]],
    rubber, 'damper-rod-wiper');

  // Dished pressed-steel lower pan supports a rubber spring isolator. The
  // outer rolled lip remains visible around the spring's closed bottom turn.
  uprightLathe([[.027, .126], [.039, .129], [.053, .140], [.078, .145],
    [.082, .151], [.081, .157], [.076, .160], [.071, .152], [.052, .149],
    [.036, .139], [.027, .139]], strutPaint, 'lower-spring-pan', 40);
  uprightLathe([[.047, .149], [.071, .151], [.074, .155], [.071, .159],
    [.047, .157], [.047, .149]], rubber, 'lower-spring-isolator', 36);

  // Corrugations are one continuous rubber surface rather than detached
  // torus rings. The rod remains visible at both boot ends.
  const bootProfile = [[.014, .225], [.024, .226]];
  for (let fold = 0; fold < 10; fold++) {
    const y = .231 + fold * .0147;
    bootProfile.push([.025, y], [.031, y + .0035], [.0315, y + .007], [.0245, y + .012]);
  }
  bootProfile.push([.025, .385], [.018, .390], [.014, .390]);
  uprightLathe(bootProfile, rubber, 'strut-accordion-dust-boot', 28);
  uprightLathe([[.011, .382], [.022, .382], [.025, .397], [.022, .409],
    [.011, .410]], mat(0x7b735f, { metalness: 0, roughness: .92 }), 'foam-bump-stop', 24);

  // The tightly seated end turns blend into a wider middle pitch, as on a
  // loaded road-car spring. The final turn lands on the upper isolator.
  const coilPoints = [];
  const turns = 5.75, coilSegments = 144;
  for (let i = 0; i <= coilSegments; i++) {
    const t = i / coilSegments;
    const a = .75 + t * turns * Math.PI * 2;
    const radius = .064 - .006 * Math.pow(t, 3);
    const easedRise = t < .10 ? t * .3
      : t > .90 ? .97 + (t - .90) * .3
        : .03 + (t - .10) * 1.175;
    coilPoints.push(new THREE.Vector3(side * radius * Math.cos(a), .164 + .239 * easedRise,
      radius * Math.sin(a)));
  }
  const coilPath = new THREE.CatmullRomCurve3(coilPoints);
  mesh(strut, new THREE.TubeGeometry(coilPath, coilSegments, .0078, 8, false),
    springPaint, 'front-coil-spring');
  uprightLathe([[.018, .398], [.052, .398], [.066, .403], [.069, .411],
    [.064, .417], [.038, .417], [.024, .423], [.018, .423]],
    strutPaint, 'upper-spring-pan', 36);
  uprightLathe([[.044, .394], [.064, .398], [.065, .405], [.047, .406], [.044, .394]],
    rubber, 'upper-spring-isolator', 32);
  uprightLathe([[.012, .419], [.039, .419], [.044, .423], [.044, .434],
    [.036, .439], [.012, .439]], zinc, 'strut-top-bearing', 36);
  uprightLathe([[.013, .433], [.035, .433], [.053, .443], [.059, .452],
    [.056, .463], [.036, .470], [.017, .470], [.013, .433]],
    rubber, 'strut-rubber-top-mount', 40);
  uprightLathe([[.012, .466], [.035, .466], [.040, .469], [.036, .474],
    [.012, .474]], zinc, 'strut-top-mount-washer', 32);
  uprightCylinder(.0118, .009, .477, zinc, 'strut-top-rod-nut', 6);
  uprightCylinder(.006, .009, .482, pinSteel, 'strut-top-threaded-rod', 18);
  for (let n = 0; n < 3; n++) {
    const angle = n * Math.PI * 2 / 3 + .7;
    const bolt = uprightCylinder(.0051, .007, .466, zinc, `top-mount-fixing-${n + 1}`, 6);
    bolt.position.x = side * .043 * Math.cos(angle);
    bolt.position.z = .043 * Math.sin(angle);
  }
  // Small welded hose bracket explains where the flexible line is supported.
  const hoseBracket = new THREE.Mesh(new THREE.BoxGeometry(.015, .020, .006), strutPaint);
  hoseBracket.name = 'strut-brake-hose-bracket';
  hoseBracket.position.set(-side * .025, .115, .031); strut.add(hoseBracket);

  // Backplate is a pressed partial annulus, leaving the caliper opening clear.
  const shield = new THREE.Shape();
  shield.absarc(0, 0, discRadius * .97, .62, Math.PI * 2 - .62, false);
  shield.absarc(0, 0, .065, Math.PI * 2 - .62, .62, true); shield.closePath();
  profile(extras, shield, -half - .010, .0012, hatMetal, 'pressed-disc-dust-shield', .0003);
  tube(extras, [[-.082, .012, .136], [-.105, .045, .122], [-.152, .076, .092],
    [-.176, .165, .032], [-.139, .195, -.005]], .0048, rubber, 'flexible-brake-hose', 30);
  axial(caliper, .0077, .014, zinc, 'brake-hose-union', -.088, .012, .136, 6);
  tube(extras, [[-.151, .175, .028], [-.152, .192, -.010], [-.144, .235, -.030]],
    .0021, zinc, 'rigid-brake-line', 16);
  tube(extras, [[-.083, .026, -.037], [-.130, .056, -.069], [-.128, .163, -.050]],
    .0025, rubber, 'abs-wheel-speed-sensor-wire', 20);
  axial(knuckle, .0046, .018, rubber, 'abs-wheel-speed-sensor', -.111, .025, -.035, 16);

  return groups;
}

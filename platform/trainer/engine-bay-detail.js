import * as THREE from 'three'

const Z_AXIS = new THREE.Vector3(0, 0, 1)

function named(object, name) {
  object.name = name
  return object
}

function roundedBoxGeometry(width, height, depth, requestedRadius = 0.012) {
  const radius = Math.max(
    0.001,
    Math.min(requestedRadius, width * 0.24, height * 0.24, depth * 0.28),
  )
  const x = width / 2 - radius
  const y = height / 2 - radius
  const shape = new THREE.Shape()
  shape.moveTo(-x, -height / 2)
  shape.lineTo(x, -height / 2)
  shape.quadraticCurveTo(width / 2, -height / 2, width / 2, -y)
  shape.lineTo(width / 2, y)
  shape.quadraticCurveTo(width / 2, height / 2, x, height / 2)
  shape.lineTo(-x, height / 2)
  shape.quadraticCurveTo(-width / 2, height / 2, -width / 2, y)
  shape.lineTo(-width / 2, -y)
  shape.quadraticCurveTo(-width / 2, -height / 2, -x, -height / 2)

  const extrusion = Math.max(0.001, depth - radius * 1.1)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: extrusion,
    bevelEnabled: true,
    bevelThickness: radius * 0.55,
    bevelSize: radius * 0.55,
    bevelSegments: 2,
    curveSegments: 6,
  })
  geometry.translate(0, 0, -extrusion / 2)
  geometry.computeVertexNormals()
  return geometry
}

function profileGeometry(points, depth, radius = 0.01) {
  const shape = new THREE.Shape()
  shape.moveTo(points[0][0], points[0][1])
  for (let index = 1; index < points.length; index += 1) {
    shape.lineTo(points[index][0], points[index][1])
  }
  shape.closePath()
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: depth - radius,
    bevelEnabled: true,
    bevelThickness: radius * 0.5,
    bevelSize: radius * 0.5,
    bevelSegments: 2,
    curveSegments: 5,
  })
  geometry.translate(0, 0, -(depth - radius) / 2)
  geometry.computeVertexNormals()
  return geometry
}

function horizontalShellGeometry(shape, thickness, bevel = 0.01) {
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: thickness,
    bevelEnabled: true,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 3,
    curveSegments: 10,
  })
  geometry.translate(0, 0, -thickness / 2)
  geometry.rotateX(-Math.PI / 2)
  geometry.computeVertexNormals()
  return geometry
}

function moldedEngineCoverGeometry(width = 0.61, depth = 0.48, segmentsX = 24, segmentsZ = 28) {
  const positions = []
  const uvs = []
  const indices = []
  const columns = segmentsX + 1
  const rows = segmentsZ + 1
  const halfWidth = width / 2
  const halfDepth = depth / 2
  const lobeCenters = [-0.6, -0.2, 0.2, 0.6]

  const sample = (column, row, top) => {
    const u = column / segmentsX * 2 - 1
    const v = row / segmentsZ * 2 - 1
    const edgeX = Math.max(0, 1 - Math.pow(Math.abs(u), 2.8))
    const edgeZ = Math.max(0, 1 - Math.pow(Math.abs(v), 3.2))
    const edgeMask = Math.pow(edgeX * edgeZ, 0.62)
    const endTaper = 1 - Math.pow(Math.abs(v), 5) * 0.11
    const x = u * halfWidth * endTaper
    const z = v * halfDepth

    if (!top) {
      return [x, -0.024 - Math.max(0, v) * edgeX * 0.009, z]
    }

    const dome = 0.018 * edgeMask
    const rearCrown = 0.006 * edgeMask * (1 - v) * 0.5
    const rearEnvelope = Math.exp(-Math.pow((v + 0.34) / 0.5, 4))
    const frontEnvelope = Math.exp(-Math.pow((v - 0.42) / 0.29, 4))
    let lobes = 0
    let channels = 0
    for (const center of lobeCenters) {
      const across = (u - center) / 0.155
      lobes += 0.014 * Math.exp(-Math.pow(across, 4)) * rearEnvelope
      channels += 0.011 * Math.exp(-Math.pow(across / 1.08, 4)) * frontEnvelope
    }
    return [x, 0.009 + dome + rearCrown + (lobes - channels) * edgeMask, z]
  }

  for (const top of [true, false]) {
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        positions.push(...sample(column, row, top))
        uvs.push(column / segmentsX, row / segmentsZ)
      }
    }
  }

  const layerVertices = columns * rows
  for (let row = 0; row < segmentsZ; row += 1) {
    for (let column = 0; column < segmentsX; column += 1) {
      const a = row * columns + column
      const b = a + 1
      const c = a + columns
      const d = c + 1
      indices.push(a, c, b, b, c, d)
      indices.push(
        layerVertices + a,
        layerVertices + b,
        layerVertices + c,
        layerVertices + b,
        layerVertices + d,
        layerVertices + c,
      )
    }
  }

  const connectEdge = (topA, topB) => {
    const bottomA = layerVertices + topA
    const bottomB = layerVertices + topB
    indices.push(topA, bottomA, topB, topB, bottomA, bottomB)
  }
  for (let column = 0; column < segmentsX; column += 1) {
    connectEdge(column + 1, column)
    const back = segmentsZ * columns
    connectEdge(back + column, back + column + 1)
  }
  for (let row = 0; row < segmentsZ; row += 1) {
    connectEdge(row * columns, (row + 1) * columns)
    connectEdge((row + 2) * columns - 1, (row + 1) * columns - 1)
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  geometry.computeBoundingSphere()
  return geometry
}

function addMesh(parent, name, geometry, material, position, rotation = [0, 0, 0]) {
  const mesh = named(new THREE.Mesh(geometry, material), name)
  mesh.position.set(...position)
  mesh.rotation.set(...rotation)
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

function addTube(parent, name, points, radius, material, tubularSegments = 20, radialSegments = 8) {
  const curve = new THREE.CatmullRomCurve3(
    points.map((point) => new THREE.Vector3(...point)),
    false,
    'centripetal',
    0.35,
  )
  const mesh = addMesh(
    parent,
    name,
    new THREE.TubeGeometry(curve, tubularSegments, radius, radialSegments, false),
    material,
    [0, 0, 0],
  )
  mesh.userData.curve = curve
  return mesh
}

function addCorrugatedHose(parent, name, points, radius, materials, ringCount = 10) {
  const hose = named(new THREE.Group(), name)
  hose.userData = { component: 'corrugated-hose', inspectable: true }
  parent.add(hose)

  const curve = new THREE.CatmullRomCurve3(
    points.map((point) => new THREE.Vector3(...point)),
    false,
    'centripetal',
    0.32,
  )
  addMesh(
    hose,
    `${name}-body`,
    new THREE.TubeGeometry(curve, 28, radius, 10, false),
    materials.rubber,
    [0, 0, 0],
  )

  const ringGeometry = new THREE.TorusGeometry(radius * 1.06, radius * 0.11, 5, 14)
  for (let index = 1; index < ringCount; index += 1) {
    const t = index / ringCount
    const ring = named(new THREE.Mesh(ringGeometry, materials.rubberEdge), `${name}-rib-${index}`)
    ring.position.copy(curve.getPointAt(t))
    ring.quaternion.setFromUnitVectors(Z_AXIS, curve.getTangentAt(t).normalize())
    ring.castShadow = true
    hose.add(ring)
  }

  for (const [suffix, t] of [['inlet', 0.035], ['outlet', 0.965]]) {
    const clamp = named(
      new THREE.Mesh(
        new THREE.TorusGeometry(radius * 1.1, 0.0045, 6, 18),
        materials.clamp,
      ),
      `${name}-${suffix}-clamp`,
    )
    clamp.position.copy(curve.getPointAt(t))
    clamp.quaternion.setFromUnitVectors(Z_AXIS, curve.getTangentAt(t).normalize())
    clamp.castShadow = true
    hose.add(clamp)
  }
  return hose
}

function makeCanvasLabel(lines) {
  if (typeof document === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 256
  const context = canvas.getContext('2d')
  if (!context) return null

  context.fillStyle = '#e9ecef'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.strokeStyle = '#9da5ad'
  context.lineWidth = 10
  context.strokeRect(10, 10, canvas.width - 20, canvas.height - 20)
  context.fillStyle = '#15191e'
  context.font = '700 58px system-ui, sans-serif'
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.fillText(lines[0], canvas.width / 2, 92)
  context.font = '600 36px system-ui, sans-serif'
  context.fillStyle = '#4b535c'
  context.fillText(lines[1], canvas.width / 2, 165)
  context.fillStyle = '#b3202b'
  context.fillRect(62, 202, canvas.width - 124, 17)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 4
  texture.needsUpdate = true
  return texture
}

function makePulley(parent, name, position, radius, width, grooves, materials) {
  const pulley = named(new THREE.Group(), name)
  pulley.position.set(...position)
  pulley.userData = {
    component: 'accessory-pulley',
    inspectable: true,
    rotationAxis: 'x',
  }
  parent.add(pulley)

  const grooveWidth = width / grooves
  for (let index = 0; index < grooves; index += 1) {
    addMesh(
      pulley,
      `${name}-groove-${index + 1}`,
      new THREE.CylinderGeometry(radius, radius, grooveWidth * 0.72, 24),
      materials.pulley,
      [-width / 2 + grooveWidth * (index + 0.5), 0, 0],
      [0, 0, Math.PI / 2],
    )
  }
  addMesh(
    pulley,
    `${name}-hub`,
    new THREE.CylinderGeometry(radius * 0.43, radius * 0.43, width * 1.08, 20),
    materials.machined,
    [0, 0, 0],
    [0, 0, Math.PI / 2],
  )
  addMesh(
    pulley,
    `${name}-center-bolt`,
    new THREE.CylinderGeometry(radius * 0.15, radius * 0.15, width * 1.25, 6),
    materials.fastener,
    [-width * 0.05, 0, 0],
    [0, 0, Math.PI / 2],
  )
  return pulley
}

function makeFanBladeGeometry() {
  const blade = new THREE.Shape()
  blade.moveTo(0.027, -0.015)
  blade.quadraticCurveTo(0.083, -0.035, 0.137, 0.009)
  blade.quadraticCurveTo(0.151, 0.031, 0.13, 0.064)
  blade.quadraticCurveTo(0.079, 0.034, 0.031, 0.021)
  blade.closePath()
  const geometry = new THREE.ExtrudeGeometry(blade, {
    depth: 0.004,
    bevelEnabled: true,
    bevelThickness: 0.0015,
    bevelSize: 0.0015,
    bevelSegments: 1,
    curveSegments: 5,
  })
  geometry.translate(0, 0, -0.002)
  geometry.computeVertexNormals()
  return geometry
}

function makeCoolingFan(parent, side, x, materials) {
  const assembly = named(new THREE.Group(), `cooling-fan-${side}-assembly`)
  assembly.position.set(x, 0, -0.041)
  assembly.userData = { component: 'cooling-fan-shroud', inspectable: true }
  parent.add(assembly)

  for (const [edge, position, width, height] of [
    ['top', [0, 0.16, -0.002], 0.32, 0.016],
    ['bottom', [0, -0.16, -0.002], 0.32, 0.016],
    ['left', [-0.16, 0, -0.002], 0.016, 0.32],
    ['right', [0.16, 0, -0.002], 0.016, 0.32],
  ]) {
    addMesh(
      assembly,
      `cooling-fan-${side}-square-shroud-${edge}`,
      roundedBoxGeometry(width, height, 0.014, 0.005),
      materials.shroud,
      position,
    )
  }
  addMesh(
    assembly,
    `cooling-fan-${side}-shroud`,
    new THREE.TorusGeometry(0.15, 0.012, 7, 40),
    materials.shroud,
    [0, 0, 0],
  )
  for (let index = 0; index < 4; index += 1) {
    addMesh(
      assembly,
      `cooling-fan-${side}-shroud-spoke-${index + 1}`,
      roundedBoxGeometry(0.3, 0.012, 0.012, 0.004),
      materials.shroud,
      [0, 0, -0.002],
      [0, 0, index * Math.PI / 4],
    )
  }

  const rotor = named(new THREE.Group(), `cooling-fan-${side}-rotor`)
  rotor.userData = {
    component: 'electric-cooling-fan',
    inspectable: true,
    rotationAxis: 'z',
  }
  assembly.add(rotor)
  const bladeGeometry = makeFanBladeGeometry()
  for (let index = 0; index < 7; index += 1) {
    const blade = named(
      new THREE.Mesh(bladeGeometry, materials.fanBlade),
      `cooling-fan-${side}-blade-${index + 1}`,
    )
    blade.rotation.z = index * Math.PI * 2 / 7
    blade.castShadow = true
    rotor.add(blade)
  }
  addMesh(
    rotor,
    `cooling-fan-${side}-hub`,
    new THREE.CylinderGeometry(0.043, 0.047, 0.028, 22),
    materials.fanBlade,
    [0, 0, -0.001],
    [Math.PI / 2, 0, 0],
  )
  return rotor
}

/**
 * Builds a constructed, typical-of-class transverse engine bay detail pass.
 * Coordinates are already in the Golf bay's world frame: +X left, +Y up,
 * +Z toward the nose. No geometry in this module is an OEM measured asset.
 */
export function buildEngineBayDetail({ materialFactory } = {}) {
  if (typeof materialFactory !== 'function') {
    throw new TypeError('buildEngineBayDetail requires a materialFactory function')
  }

  const material = (name, color, options, finish) => {
    const result = materialFactory(color, options, finish)
    if (!result || result.isMaterial !== true) {
      throw new TypeError(`materialFactory did not return a THREE.Material for ${name}`)
    }
    result.name = name
    return result
  }

  const materials = {
    cast: material('detail-cast-alloy', 0x4b535b, { roughness: 0.76, metalness: 0.28 }, 'cast'),
    darkCast: material('detail-dark-casting', 0x343a41, { roughness: 0.79, metalness: 0.32 }, 'cast'),
    machined: material('detail-machined-alloy', 0x9098a0, { roughness: 0.38, metalness: 0.82 }, 'brushed'),
    fastener: material('detail-zinc-fasteners', 0xa7adb3, { roughness: 0.35, metalness: 0.9 }, 'brushed'),
    plastic: material('detail-black-plastic', 0x07090c, { roughness: 0.89, metalness: 0.015 }, 'plastic'),
    plasticEdge: material('detail-plastic-highlight', 0x11151a, { roughness: 0.8, metalness: 0.025 }, 'plastic'),
    inlet: material('detail-intake-composite', 0x333941, { roughness: 0.77, metalness: 0.04 }, 'plastic'),
    rubber: material('detail-rubber', 0x111419, { roughness: 0.96, metalness: 0.01 }, 'rubber'),
    rubberEdge: material('detail-rubber-ribs', 0x20242a, { roughness: 0.9, metalness: 0.02 }, 'rubber'),
    loom: material('detail-wiring-loom', 0x0c0f13, { roughness: 0.92, metalness: 0.02 }, 'rubber'),
    connector: material('detail-electrical-connectors', 0x252b32, { roughness: 0.74, metalness: 0.05 }, 'plastic'),
    clamp: material('detail-hose-clamps', 0xa4abb2, { roughness: 0.31, metalness: 0.88 }, 'brushed'),
    pulley: material('detail-pulley-steel', 0x292f35, { roughness: 0.52, metalness: 0.56 }, 'brushed'),
    battery: material('detail-battery-case', 0x181c21, { roughness: 0.84, metalness: 0.03 }, 'plastic'),
    batteryTop: material('detail-battery-lid', 0x292f36, { roughness: 0.68, metalness: 0.06 }, 'plastic'),
    positive: material('detail-positive-terminal', 0xa8222d, { roughness: 0.43, metalness: 0.3 }, 'paint'),
    copper: material('detail-copper', 0xb87333, { roughness: 0.32, metalness: 0.9 }, 'brushed'),
    coolantTank: material('detail-coolant-tank', 0xdbe2df, {
      transparent: true,
      opacity: 0.48,
      roughness: 0.31,
      metalness: 0,
      transmission: 0.1,
      depthWrite: false,
    }, 'plastic'),
    coolantFluid: material('detail-pink-coolant', 0xea6385, {
      transparent: true,
      opacity: 0.68,
      roughness: 0.24,
      metalness: 0,
      depthWrite: false,
    }, 'plastic'),
    capBlue: material('detail-reservoir-cap', 0x285c9f, { roughness: 0.48, metalness: 0.08 }, 'plastic'),
    radiator: material('detail-radiator-alloy', 0x747d85, { roughness: 0.48, metalness: 0.75 }, 'brushed'),
    radiatorDark: material('detail-radiator-shadow', 0x242a30, { roughness: 0.7, metalness: 0.35 }, 'cast'),
    shroud: material('detail-fan-shroud', 0x171c22, { roughness: 0.84, metalness: 0.03 }, 'plastic'),
    fanBlade: material('detail-fan-blades', 0x222830, { roughness: 0.76, metalness: 0.04 }, 'plastic'),
    oilMark: material('detail-service-marking', 0xe1b63c, { roughness: 0.45, metalness: 0.18 }, 'paint'),
    bodyPaint: material('detail-shadowed-body-paint', 0x861923, { roughness: 0.38, metalness: 0.1 }, 'paint'),
    insulation: material('detail-bulkhead-insulation', 0x11151a, { roughness: 0.93, metalness: 0.02 }, 'rubber'),
    foil: material('detail-bulkhead-heat-shield', 0xc6cdd3, { roughness: 0.55, metalness: 0.3 }, 'brushed'),
  }

  const group = named(new THREE.Group(), 'engine-bay-detail')
  group.userData = {
    component: 'constructed-engine-bay-detail',
    inspectable: true,
    sourceType: 'constructed-training-geometry',
    coordinateSystem: '+X left, +Y up, +Z nose',
    accuracy: 'typical-of-class; not an OEM measured EA888 model',
  }

  /* Root keeps the original red inner-wing liners but removes the old bay
     filler geometry. These lower rails, towers and bulkhead stop the detailed
     engine from floating in the exterior shell without re-creating those
     preserved side liners. */
  const structure = named(new THREE.Group(), 'engine-bay-structure')
  structure.userData = { component: 'bay-structure-and-heat-shield', inspectable: true }
  group.add(structure)
  addMesh(
    structure,
    'bulkhead-insulation-panel',
    roundedBoxGeometry(1.02, 0.31, 0.028, 0.018),
    materials.insulation,
    [0, 0.65, 1.154],
  )
  addMesh(
    structure,
    'bulkhead-aluminium-heat-shield-backing',
    roundedBoxGeometry(0.84, 0.245, 0.01, 0.004),
    materials.foil,
    [0.015, 0.685, 1.174],
  )
  const heatShieldRidges = named(
    new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.013, 0.23, 0.014),
      materials.foil,
      27,
    ),
    'bulkhead-heat-shield-corrugations',
  )
  const structureMatrix = new THREE.Matrix4()
  for (let index = 0; index < 27; index += 1) {
    structureMatrix.makeTranslation(-0.385 + index * 0.03, 0.685, 1.181)
    heatShieldRidges.setMatrixAt(index, structureMatrix)
  }
  heatShieldRidges.instanceMatrix.needsUpdate = true
  structure.add(heatShieldRidges)
  addMesh(
    structure,
    'bulkhead-heat-shield-top-roll',
    new THREE.CylinderGeometry(0.011, 0.011, 0.86, 12),
    materials.foil,
    [0.015, 0.816, 1.179],
    [0, 0, Math.PI / 2],
  )
  for (const [side, x] of [['left', -0.455], ['right', 0.455]]) {
    addMesh(
      structure,
      `lower-${side}-chassis-rail`,
      roundedBoxGeometry(0.09, 0.068, 0.7, 0.018),
      materials.darkCast,
      [x, 0.36, 1.57],
    )
  }
  addMesh(
    structure,
    'lower-front-crossmember',
    roundedBoxGeometry(1.02, 0.073, 0.08, 0.018),
    materials.darkCast,
    [0, 0.36, 1.93],
  )
  addMesh(
    structure,
    'lower-rear-crossmember',
    roundedBoxGeometry(0.91, 0.062, 0.07, 0.016),
    materials.darkCast,
    [0, 0.355, 1.205],
  )
  for (const [side, x] of [['left', -0.5], ['right', 0.5]]) {
    const tower = named(new THREE.Group(), `suspension-${side}-strut-tower`)
    tower.position.set(x, 0.675, 1.42)
    tower.userData = { component: 'strut-top', inspectable: true }
    structure.add(tower)
    addMesh(
      tower,
      `suspension-${side}-tower-cup`,
      new THREE.CylinderGeometry(0.086, 0.078, 0.082, 24),
      materials.bodyPaint,
      [0, 0, 0],
    )
    addMesh(
      tower,
      `suspension-${side}-tower-ring`,
      new THREE.TorusGeometry(0.061, 0.009, 7, 22),
      materials.machined,
      [0, 0.046, 0],
      [Math.PI / 2, 0, 0],
    )
    for (let index = 0; index < 3; index += 1) {
      const angle = index * Math.PI * 2 / 3
      addMesh(
        tower,
        `suspension-${side}-top-nut-${index + 1}`,
        new THREE.CylinderGeometry(0.009, 0.009, 0.014, 6),
        materials.fastener,
        [Math.cos(angle) * 0.058, 0.052, Math.sin(angle) * 0.058],
      )
    }
  }

  /* Engine castings: irregular profiles, flange lines, ribs and bosses keep
     the long block readable without relying on a large rectangular shell. */
  const engine = named(new THREE.Group(), 'engine-long-block')
  engine.position.set(0, 0.53, 1.52)
  engine.userData = {
    component: 'transverse-inline-four',
    inspectable: true,
    visualForm: 'compound-rounded-casting',
  }
  group.add(engine)

  const crankcaseGeometry = new THREE.CapsuleGeometry(0.12, 0.4, 7, 20)
  crankcaseGeometry.rotateZ(Math.PI / 2)
  crankcaseGeometry.scale(1, 1, 1.25)
  crankcaseGeometry.userData.form = 'rounded-cylinder-bank-casting'
  addMesh(
    engine,
    'crankcase-main-casting',
    crankcaseGeometry,
    materials.cast,
    [0, 0, 0],
  )

  const cylinderBankCrown = new THREE.CapsuleGeometry(0.073, 0.424, 6, 18)
  cylinderBankCrown.rotateZ(Math.PI / 2)
  cylinderBankCrown.scale(1, 1, 1.62)
  addMesh(
    engine,
    'crankcase-cylinder-bank-crown',
    cylinderBankCrown,
    materials.darkCast,
    [-0.005, 0.096, -0.006],
  )

  const timingSideCasting = addMesh(
    engine,
    'timing-side-lower-casting',
    new THREE.SphereGeometry(1, 22, 12),
    materials.cast,
    [0.292, -0.022, 0.006],
  )
  timingSideCasting.scale.set(0.064, 0.116, 0.138)

  const headGeometry = new THREE.CapsuleGeometry(0.082, 0.416, 7, 20)
  headGeometry.rotateZ(Math.PI / 2)
  headGeometry.scale(1, 1, 1.65)
  headGeometry.userData.form = 'sculpted-crossflow-head'
  addMesh(
    engine,
    'cylinder-head-casting',
    headGeometry,
    materials.darkCast,
    [0, 0.19, -0.002],
  )
  const headFrontDeck = new THREE.CapsuleGeometry(0.035, 0.458, 5, 16)
  headFrontDeck.rotateZ(Math.PI / 2)
  headFrontDeck.scale(1, 1, 0.34)
  addMesh(
    engine,
    'cylinder-head-front-deck',
    headFrontDeck,
    materials.machined,
    [0, 0.177, 0.145],
  )
  for (const [side, x] of [['left', -0.27], ['right', 0.27]]) {
    const endCap = addMesh(
      engine,
      `cylinder-head-${side}-end-cap`,
      new THREE.SphereGeometry(1, 18, 10),
      materials.cast,
      [x, 0.19, -0.004],
    )
    endCap.scale.set(0.045, 0.079, 0.126)
  }
  addMesh(
    engine,
    'exhaust-side-formed-heat-shield',
    roundedBoxGeometry(0.43, 0.105, 0.018, 0.026),
    materials.foil,
    [-0.015, 0.115, -0.164],
    [-0.04, 0, 0],
  )
  addMesh(
    engine,
    'oil-sump-flange',
    roundedBoxGeometry(0.56, 0.028, 0.3, 0.009),
    materials.machined,
    [0, -0.135, 0.005],
  )
  addMesh(
    engine,
    'pressed-oil-sump',
    profileGeometry([
      [-0.27, 0.055], [0.27, 0.055], [0.245, -0.09], [0.18, -0.125],
      [-0.19, -0.125], [-0.255, -0.085],
    ], 0.275, 0.015),
    materials.darkCast,
    [0, -0.18, 0.006],
  )

  for (const z of [-0.158, 0.158]) {
    addMesh(
      engine,
      z > 0 ? 'crankcase-front-split-line' : 'crankcase-rear-split-line',
      roundedBoxGeometry(0.59, 0.012, 0.009, 0.003),
      materials.machined,
      [0, 0.067, z],
    )
  }
  for (const x of [-0.302, 0.302]) {
    addMesh(
      engine,
      x > 0 ? 'crankcase-left-split-return' : 'crankcase-right-split-return',
      roundedBoxGeometry(0.009, 0.012, 0.3, 0.003),
      materials.machined,
      [x, 0.067, 0],
    )
  }

  const ribGeometry = roundedBoxGeometry(0.021, 0.135, 0.014, 0.004)
  for (let index = 0; index < 8; index += 1) {
    addMesh(
      engine,
      `crankcase-stiffening-rib-${index + 1}`,
      ribGeometry,
      materials.cast,
      [-0.245 + index * 0.07, -0.006, 0.16],
      [0, 0, index % 2 === 0 ? -0.08 : 0.08],
    )
  }

  const bossGeometry = new THREE.CylinderGeometry(0.021, 0.024, 0.016, 16)
  for (const [index, x, y] of [
    [1, -0.25, 0.085], [2, -0.13, -0.075], [3, 0, 0.09],
    [4, 0.13, -0.075], [5, 0.25, 0.085],
  ]) {
    addMesh(
      engine,
      `crankcase-bolt-boss-${index}`,
      bossGeometry,
      materials.machined,
      [x, y, 0.163],
      [Math.PI / 2, 0, 0],
    )
  }

  const sumpBoltPositions = []
  for (const x of [-0.235, -0.14, -0.047, 0.047, 0.14, 0.235]) {
    sumpBoltPositions.push([x, -0.116, -0.136], [x, -0.116, 0.146])
  }
  sumpBoltPositions.push([-0.268, -0.116, -0.07], [-0.268, -0.116, 0.07])
  sumpBoltPositions.push([0.268, -0.116, -0.07], [0.268, -0.116, 0.07])
  const sumpBolts = named(
    new THREE.InstancedMesh(
      new THREE.CylinderGeometry(0.007, 0.007, 0.012, 6),
      materials.fastener,
      sumpBoltPositions.length,
    ),
    'sump-perimeter-bolts',
  )
  const boltMatrix = new THREE.Matrix4()
  sumpBoltPositions.forEach((position, index) => {
    boltMatrix.makeTranslation(...position)
    sumpBolts.setMatrixAt(index, boltMatrix)
  })
  sumpBolts.castShadow = true
  sumpBolts.instanceMatrix.needsUpdate = true
  engine.add(sumpBolts)

  /* A shallow bellhousing flange meets, but does not replace or cover, the
     existing generated starter at (-.50, .445, 1.60). */
  const bellhousing = named(new THREE.Group(), 'bellhousing-starter-interface')
  bellhousing.position.set(-0.35, -0.025, 0.075)
  bellhousing.userData = { component: 'bellhousing-interface', inspectable: true }
  engine.add(bellhousing)
  addMesh(
    bellhousing,
    'bellhousing-cast-shell',
    new THREE.CylinderGeometry(0.15, 0.135, 0.075, 30, 1, false, 0.25, Math.PI * 1.5),
    materials.cast,
    [0, 0, 0],
    [0, 0, Math.PI / 2],
  )
  for (const [index, y, z] of [[1, 0.1, -0.08], [2, 0.1, 0.08], [3, -0.1, -0.08], [4, -0.1, 0.08]]) {
    addMesh(
      bellhousing,
      `bellhousing-fastener-${index}`,
      new THREE.CylinderGeometry(0.009, 0.009, 0.018, 6),
      materials.fastener,
      [-0.041, y, z],
      [0, 0, Math.PI / 2],
    )
  }

  /* The cam/valve cover is a permanent engine component. Diagnosis removes
     the separate cosmetic cover below, never this casting or its oil cap. */
  const valveCover = named(new THREE.Group(), 'moulded-four-coil-valve-cover')
  valveCover.position.set(0, 0.77, 1.52)
  valveCover.rotation.x = -0.065
  valveCover.userData = {
    component: 'moulded-four-coil-valve-cover',
    inspectable: true,
    persistent: true,
    constructed: true,
  }
  group.add(valveCover)

  const coverShape = new THREE.Shape()
  coverShape.moveTo(-0.292, -0.13)
  coverShape.lineTo(-0.238, -0.168)
  coverShape.lineTo(0.225, -0.168)
  coverShape.quadraticCurveTo(0.302, -0.155, 0.31, -0.09)
  coverShape.lineTo(0.286, 0.112)
  coverShape.quadraticCurveTo(0.255, 0.153, 0.19, 0.158)
  coverShape.lineTo(-0.245, 0.148)
  coverShape.quadraticCurveTo(-0.3, 0.125, -0.305, 0.065)
  coverShape.closePath()
  const valveCoverFlange = addMesh(
    valveCover,
    'valve-cover-perimeter-flange',
    horizontalShellGeometry(coverShape, 0.022, 0.008),
    materials.plasticEdge,
    [0, -0.024, 0],
  )
  valveCoverFlange.scale.set(1.015, 1, 1.015)

  const valveCoverGeometry = moldedEngineCoverGeometry(0.6, 0.32, 22, 20)
  valveCoverGeometry.userData.form = 'sloped-moulded-cam-cover'
  addMesh(
    valveCover,
    'valve-cover-moulded-shell',
    valveCoverGeometry,
    materials.plastic,
    [0, 0, 0],
  )
  addMesh(
    valveCover,
    'valve-cover-raised-spine',
    roundedBoxGeometry(0.47, 0.02, 0.068, 0.012),
    materials.plasticEdge,
    [-0.012, 0.044, -0.015],
  )
  for (let index = 0; index < 4; index += 1) {
    addMesh(
      valveCover,
      `valve-cover-moulded-rib-${index + 1}`,
      roundedBoxGeometry(0.025, 0.012, 0.18, 0.005),
      materials.plasticEdge,
      [-0.14 + index * 0.09, 0.045, 0.012],
      [0, 0.08, 0],
    )
  }
  const coilXs = [-0.205, -0.068, 0.068, 0.205]
  coilXs.forEach((x, index) => {
    addMesh(
      valveCover,
      `valve-cover-coil-well-${index + 1}`,
      new THREE.TorusGeometry(0.025, 0.0045, 7, 20),
      materials.rubber,
      [x, 0.042, 0.012],
      [Math.PI / 2, 0, 0],
    )
  })
  const coverFastenerPositions = [
    [-0.255, -0.115], [-0.09, -0.145], [0.09, -0.145], [0.255, -0.105],
    [-0.255, 0.11], [-0.09, 0.14], [0.09, 0.14], [0.255, 0.105],
  ]
  coverFastenerPositions.forEach(([x, z], index) => {
    addMesh(
      valveCover,
      `valve-cover-perimeter-fastener-${index + 1}`,
      new THREE.CylinderGeometry(0.007, 0.008, 0.012, 8),
      materials.fastener,
      [x, 0.038, z],
    )
  })
  addMesh(
    valveCover,
    'oil-filler-neck',
    new THREE.CylinderGeometry(0.035, 0.039, 0.025, 22),
    materials.plasticEdge,
    [0.325, 0.054, -0.105],
  )
  const oilCap = addMesh(
    valveCover,
    'oil-filler-cap',
    new THREE.CylinderGeometry(0.043, 0.043, 0.022, 24),
    materials.plastic,
    [0.325, 0.075, -0.105],
  )
  oilCap.userData = { component: 'oil-filler-cap', inspectable: true }
  addMesh(
    valveCover,
    'oil-cap-service-ring',
    new THREE.TorusGeometry(0.027, 0.0045, 6, 20),
    materials.oilMark,
    [0.325, 0.087, -0.105],
    [Math.PI / 2, 0, 0],
  )

  const ignition = named(new THREE.Group(), 'four-coil-ignition-assembly')
  ignition.userData = { component: 'coil-on-plug-ignition', inspectable: true }
  group.add(ignition)
  coilXs.forEach((x, index) => {
    const coil = named(new THREE.Group(), `ignition-coil-${index + 1}`)
    coil.position.set(x, 0.82, 1.515)
    coil.userData = { component: 'ignition-coil', cylinder: index + 1, inspectable: true }
    ignition.add(coil)
    addMesh(
      coil,
      `ignition-coil-${index + 1}-body`,
      roundedBoxGeometry(0.052, 0.033, 0.072, 0.008),
      materials.connector,
      [0, 0, 0],
    )
    const shoulderGeometry = new THREE.CapsuleGeometry(0.014, 0.035, 5, 12)
    shoulderGeometry.rotateX(Math.PI / 2)
    shoulderGeometry.scale(1.35, 1, 1)
    addMesh(
      coil,
      `ignition-coil-${index + 1}-upper-shoulder`,
      shoulderGeometry,
      materials.connector,
      [0, 0.008, -0.006],
    )
    addMesh(
      coil,
      `ignition-coil-${index + 1}-stem`,
      new THREE.CylinderGeometry(0.013, 0.016, 0.052, 14),
      materials.connector,
      [0, -0.031, 0.015],
    )
    addMesh(
      coil,
      `ignition-coil-${index + 1}-boot`,
      new THREE.CylinderGeometry(0.011, 0.0135, 0.052, 14),
      materials.rubber,
      [0, -0.077, 0.015],
    )
    addMesh(
      coil,
      `ignition-coil-${index + 1}-well-seal`,
      new THREE.TorusGeometry(0.019, 0.005, 6, 16),
      materials.rubber,
      [0, -0.018, 0.018],
      [Math.PI / 2, 0, 0],
    )
    addMesh(
      coil,
      `ignition-coil-${index + 1}-connector`,
      roundedBoxGeometry(0.036, 0.027, 0.038, 0.006),
      materials.connector,
      [0, 0.006, -0.052],
    )
    addMesh(
      coil,
      `ignition-coil-${index + 1}-connector-lock`,
      roundedBoxGeometry(0.022, 0.009, 0.019, 0.003),
      materials.positive,
      [0, 0.023, -0.064],
    )
  })

  /* The supplied Mk8 reference is dominated by one broad, low black moulding.
     This is the BAY.cover action target; removing it exposes the four coils,
     harness and the permanent cam cover above. */
  const cover = named(new THREE.Group(), 'cosmetic-engine-cover-removable')
  cover.position.set(-0.008, 0.86, 1.54)
  cover.rotation.x = -0.018
  cover.userData = {
    component: 'cosmetic-engine-cover',
    inspectable: true,
    removable: true,
    constructed: true,
    surfaceFeatures: 'four blended rear lobes and four recessed front channels',
  }
  group.add(cover)
  addMesh(
    cover,
    'cosmetic-cover-sculpted-shell',
    moldedEngineCoverGeometry(),
    materials.plastic,
    [0, 0, 0],
  )

  /* Circular badge toward the reference's viewer-left/rear quadrant. */
  addMesh(
    cover,
    'cosmetic-cover-vw-badge-ring',
    new THREE.TorusGeometry(0.034, 0.0045, 7, 28),
    materials.machined,
    [-0.222, 0.035, -0.185],
    [Math.PI / 2, 0, 0],
  )
  addMesh(
    cover,
    'cosmetic-cover-vw-badge-field',
    new THREE.CylinderGeometry(0.03, 0.03, 0.006, 28),
    materials.plasticEdge,
    [-0.222, 0.035, -0.185],
  )
  for (const [index, x, z, angle] of [
    [1, -0.233, -0.192, -0.48],
    [2, -0.211, -0.192, 0.48],
    [3, -0.233, -0.176, 0.48],
    [4, -0.211, -0.176, -0.48],
  ]) {
    addMesh(
      cover,
      `cosmetic-cover-vw-stroke-${index}`,
      roundedBoxGeometry(0.005, 0.005, 0.029, 0.002),
      materials.machined,
      [x, 0.041, z],
      [0, angle, 0],
    )
  }
  /* Four separate swept runners lead from a ribbed plenum to the head. */
  const intake = named(new THREE.Group(), 'intake-manifold')
  intake.userData = { component: 'four-runner-intake-manifold', inspectable: true }
  group.add(intake)
  addMesh(
    intake,
    'intake-plenum',
    roundedBoxGeometry(0.5, 0.115, 0.13, 0.025),
    materials.inlet,
    [0, 0.67, 1.245],
  )
  for (let index = 0; index < 6; index += 1) {
    addMesh(
      intake,
      `intake-plenum-rib-${index + 1}`,
      roundedBoxGeometry(0.018, 0.12, 0.014, 0.004),
      materials.plasticEdge,
      [-0.195 + index * 0.078, 0.67, 1.312],
    )
  }
  coilXs.forEach((x, index) => {
    addTube(
      intake,
      `intake-runner-cylinder-${index + 1}`,
      [
        [x, 0.69, 1.3],
        [x * 1.07, 0.61, 1.285],
        [x * 1.04, 0.57, 1.34],
        [x, 0.665, 1.395],
      ],
      0.028,
      materials.inlet,
      18,
      10,
    )
  })
  addMesh(
    intake,
    'electronic-throttle-body',
    new THREE.CylinderGeometry(0.055, 0.055, 0.065, 24),
    materials.machined,
    [0.285, 0.685, 1.245],
    [0, 0, Math.PI / 2],
  )
  addMesh(
    intake,
    'throttle-actuator',
    roundedBoxGeometry(0.046, 0.057, 0.052, 0.01),
    materials.connector,
    [0.302, 0.732, 1.245],
  )

  const airbox = named(new THREE.Group(), 'airbox-assembly')
  airbox.userData = { component: 'air-filter-housing', inspectable: true }
  group.add(airbox)
  const airboxShape = new THREE.Shape()
  airboxShape.moveTo(-0.13, -0.105)
  airboxShape.lineTo(0.112, -0.118)
  airboxShape.quadraticCurveTo(0.145, -0.105, 0.147, -0.064)
  airboxShape.lineTo(0.132, 0.098)
  airboxShape.lineTo(-0.105, 0.118)
  airboxShape.quadraticCurveTo(-0.14, 0.103, -0.142, 0.064)
  airboxShape.closePath()
  addMesh(
    airbox,
    'airbox-lower-case',
    horizontalShellGeometry(airboxShape, 0.085, 0.014),
    materials.plastic,
    [0.415, 0.82, 1.7],
  )
  addMesh(
    airbox,
    'airbox-lid',
    horizontalShellGeometry(airboxShape, 0.042, 0.01),
    materials.plasticEdge,
    [0.415, 0.875, 1.7],
  )
  for (let index = 0; index < 5; index += 1) {
    addMesh(
      airbox,
      `airbox-lid-rib-${index + 1}`,
      roundedBoxGeometry(0.018, 0.01, 0.185, 0.004),
      materials.plastic,
      [0.335 + index * 0.04, 0.903, 1.7],
    )
  }
  for (const [index, x, z] of [[1, 0.29, 1.62], [2, 0.53, 1.62], [3, 0.3, 1.78], [4, 0.52, 1.78]]) {
    addMesh(
      airbox,
      `airbox-spring-clip-${index}`,
      roundedBoxGeometry(0.026, 0.025, 0.012, 0.004),
      materials.clamp,
      [x, 0.87, z],
    )
  }
  addCorrugatedHose(
    group,
    'airbox-to-throttle-duct',
    [
      [0.315, 0.84, 1.68],
      [0.355, 0.845, 1.59],
      [0.36, 0.79, 1.43],
      [0.29, 0.695, 1.29],
    ],
    0.046,
    materials,
    10,
  )

  const battery = named(new THREE.Group(), 'battery-assembly')
  battery.userData = { component: 'low-voltage-battery', inspectable: true }
  group.add(battery)
  addMesh(
    battery,
    'battery-case',
    roundedBoxGeometry(0.31, 0.19, 0.22, 0.024),
    materials.battery,
    [0.4, 0.64, 1.27],
  )
  addMesh(
    battery,
    'battery-lid',
    roundedBoxGeometry(0.314, 0.025, 0.224, 0.009),
    materials.batteryTop,
    [0.4, 0.747, 1.27],
  )
  addMesh(
    battery,
    'battery-hold-down-bar',
    roundedBoxGeometry(0.32, 0.024, 0.035, 0.007),
    materials.fastener,
    [0.4, 0.545, 1.366],
  )
  for (const [side, x] of [['left', 0.255], ['right', 0.545]]) {
    addMesh(
      battery,
      `battery-hold-down-${side}-bolt`,
      new THREE.CylinderGeometry(0.008, 0.008, 0.18, 8),
      materials.fastener,
      [x, 0.62, 1.366],
    )
  }

  const terminals = [
    ['positive', 0.28, 1.22, materials.positive],
    ['negative', 0.51, 1.22, materials.fastener],
  ]
  for (const [terminal, x, z, terminalMaterial] of terminals) {
    const post = addMesh(
      battery,
      `battery-${terminal}-post`,
      new THREE.CylinderGeometry(0.014, 0.017, 0.036, 14),
      terminalMaterial,
      [x, 0.775, z],
    )
    post.userData = { component: `battery-${terminal}-terminal`, inspectable: true }
    addMesh(
      battery,
      `battery-${terminal}-clamp`,
      new THREE.TorusGeometry(0.022, 0.006, 7, 18),
      materials.clamp,
      [x, 0.783, z],
      [Math.PI / 2, 0, 0],
    )
  }
  addMesh(
    battery,
    'battery-positive-terminal-cover',
    roundedBoxGeometry(0.075, 0.027, 0.064, 0.011),
    materials.positive,
    [0.28, 0.798, 1.22],
  )

  const labelTexture = makeCanvasLabel(['12 V AGM', 'TRAINING BATTERY'])
  const labelMaterial = material(
    'detail-battery-label',
    0xe9ecef,
    {
      roughness: 0.68,
      metalness: 0,
      ...(labelTexture ? { map: labelTexture } : {}),
      side: THREE.DoubleSide,
    },
    'plastic',
  )
  addMesh(
    battery,
    'battery-rating-label',
    new THREE.PlaneGeometry(0.142, 0.068),
    labelMaterial,
    [0.4, 0.763, 1.29],
    [-Math.PI / 2, 0, 0],
  )

  /* The old starter cable terminates at the same positive-post vicinity, so
     the replacement battery meets the preserved starter rather than floating. */
  addTube(
    group,
    'battery-positive-cable-to-starter',
    [
      [0.28, 0.78, 1.22],
      [0.08, 0.755, 1.27],
      [-0.34, 0.68, 1.36],
      [-0.54, 0.59, 1.45],
      [-0.562, 0.509, 1.6],
    ],
    0.012,
    materials.positive,
    22,
    9,
  )
  addTube(
    group,
    'battery-negative-earth-lead',
    [
      [0.51, 0.78, 1.22],
      [0.49, 0.65, 1.28],
      [0.34, 0.49, 1.35],
    ],
    0.011,
    materials.rubber,
    16,
    8,
  )

  /* Harness trunk, four coil drops and positive-lock connector blocks. */
  const wiring = named(new THREE.Group(), 'engine-wiring-harness')
  wiring.position.y = -0.075
  wiring.userData = { component: 'engine-wiring-harness', inspectable: true }
  group.add(wiring)
  addTube(
    wiring,
    'engine-harness-main-trunk',
    [
      [-0.31, 0.895, 1.405],
      [-0.15, 0.91, 1.39],
      [0.08, 0.905, 1.4],
      [0.3, 0.875, 1.43],
    ],
    0.014,
    materials.loom,
    22,
    8,
  )
  coilXs.forEach((x, index) => {
    addTube(
      wiring,
      `coil-${index + 1}-harness-branch`,
      [
        [x, 0.9, 1.4],
        [x, 0.905, 1.45],
        [x, 0.888, 1.475],
      ],
      0.006,
      materials.loom,
      10,
      7,
    )
    addMesh(
      wiring,
      `coil-${index + 1}-locking-connector`,
      roundedBoxGeometry(0.035, 0.025, 0.038, 0.005),
      materials.connector,
      [x, 0.892, 1.475],
    )
  })
  addTube(
    wiring,
    'engine-harness-front-drop',
    [
      [0.3, 0.875, 1.43],
      [0.34, 0.81, 1.53],
      [0.33, 0.7, 1.66],
    ],
    0.011,
    materials.loom,
    16,
    8,
  )

  /* Accessory drive shares the existing generated alternator's belt plane:
     world X .345, with that alternator's pulley at approximately Y .70/Z 1.72. */
  const accessoryDrive = named(new THREE.Group(), 'accessory-drive')
  accessoryDrive.userData = { component: 'serpentine-accessory-drive', inspectable: true }
  group.add(accessoryDrive)
  const pulleys = [
    makePulley(accessoryDrive, 'crankshaft-damper-pulley', [0.345, 0.435, 1.635], 0.071, 0.042, 6, materials),
    makePulley(accessoryDrive, 'automatic-tensioner-pulley', [0.345, 0.56, 1.57], 0.043, 0.031, 5, materials),
    makePulley(accessoryDrive, 'accessory-idler-pulley', [0.345, 0.585, 1.79], 0.037, 0.028, 4, materials),
  ]
  const beltPoints = [
    [0.345, 0.37, 1.62],
    [0.345, 0.42, 1.565],
    [0.345, 0.55, 1.525],
    [0.345, 0.67, 1.65],
    [0.345, 0.705, 1.72],
    [0.345, 0.635, 1.79],
    [0.345, 0.56, 1.825],
    [0.345, 0.44, 1.7],
  ]
  for (const [index, xOffset] of [[1, -0.0045], [2, 0.0045]]) {
    const curve = new THREE.CatmullRomCurve3(
      beltPoints.map(([x, y, z]) => new THREE.Vector3(x + xOffset, y, z)),
      true,
      'centripetal',
      0.28,
    )
    addMesh(
      accessoryDrive,
      `serpentine-belt-rib-${index}`,
      new THREE.TubeGeometry(curve, 52, 0.004, 6, true),
      materials.rubber,
      [0, 0, 0],
    )
  }

  /* Thin radiator/condenser layers, tanks and rear shrouds. */
  const radiator = named(new THREE.Group(), 'radiator-condenser-cooling-pack')
  radiator.position.set(0, 0.56, 1.91)
  radiator.userData = { component: 'cooling-pack', inspectable: true }
  group.add(radiator)
  addMesh(
    radiator,
    'radiator-top-rail',
    roundedBoxGeometry(0.98, 0.035, 0.052, 0.008),
    materials.radiatorDark,
    [0, 0.174, 0],
  )
  const bonnetLatch = named(new THREE.Group(), 'slam-panel-bonnet-latch')
  bonnetLatch.position.set(0, 0.18, 0.028)
  bonnetLatch.userData = { component: 'bonnet-latch', inspectable: true }
  radiator.add(bonnetLatch)
  addMesh(
    bonnetLatch,
    'bonnet-latch-carrier',
    roundedBoxGeometry(0.13, 0.042, 0.028, 0.009),
    materials.radiatorDark,
    [0, 0, 0],
  )
  addMesh(
    bonnetLatch,
    'bonnet-latch-loop',
    new THREE.TorusGeometry(0.026, 0.005, 6, 18, Math.PI * 1.4),
    materials.fastener,
    [0, 0.018, -0.014],
    [Math.PI / 2, 0, -Math.PI * 0.2],
  )
  addMesh(
    radiator,
    'radiator-bottom-rail',
    roundedBoxGeometry(0.98, 0.035, 0.052, 0.008),
    materials.radiatorDark,
    [0, -0.174, 0],
  )
  for (const [side, x] of [['left', -0.49], ['right', 0.49]]) {
    addMesh(
      radiator,
      `radiator-${side}-side-tank`,
      roundedBoxGeometry(0.065, 0.35, 0.066, 0.018),
      materials.shroud,
      [x, 0, -0.004],
    )
  }

  addMesh(
    radiator,
    'radiator-dark-core-backing',
    roundedBoxGeometry(0.9, 0.307, 0.018, 0.006),
    materials.radiatorDark,
    [0, 0, -0.004],
  )

  /* Real cores read as dense horizontal foil, not an egg-crate. A small set
     of very slim coolant tubes supports ninety-six fine fins over a dark core. */
  const coolantTubes = named(
    new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.003, 0.304, 0.008),
      materials.radiator,
      22,
    ),
    'radiator-slim-coolant-tubes',
  )
  for (let index = 0; index < 22; index += 1) {
    boltMatrix.makeTranslation(-0.42 + index * 0.04, 0, 0.008)
    coolantTubes.setMatrixAt(index, boltMatrix)
  }
  coolantTubes.instanceMatrix.needsUpdate = true
  coolantTubes.receiveShadow = true
  radiator.add(coolantTubes)

  const horizontalFinGeometry = new THREE.BoxGeometry(0.88, 0.0015, 0.006)
  const horizontalFins = named(
    new THREE.InstancedMesh(horizontalFinGeometry, materials.radiator, 96),
    'radiator-dense-horizontal-fins',
  )
  for (let index = 0; index < 96; index += 1) {
    boltMatrix.makeTranslation(0, -0.151 + index * (0.302 / 95), 0.012)
    horizontalFins.setMatrixAt(index, boltMatrix)
  }
  horizontalFins.instanceMatrix.needsUpdate = true
  horizontalFins.receiveShadow = true
  radiator.add(horizontalFins)

  const condenserFins = named(
    new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.875, 0.001, 0.004),
      materials.machined,
      72,
    ),
    'condenser-dense-horizontal-fins',
  )
  for (let index = 0; index < 72; index += 1) {
    boltMatrix.makeTranslation(0, -0.149 + index * (0.298 / 71), 0.027)
    condenserFins.setMatrixAt(index, boltMatrix)
  }
  condenserFins.instanceMatrix.needsUpdate = true
  condenserFins.receiveShadow = true
  radiator.add(condenserFins)

  const fans = [makeCoolingFan(radiator, 'main', -0.15, materials)]

  /* Hoses route around the preserved alternator rather than through it. */
  addTube(
    group,
    'radiator-upper-hose',
    [
      [0.27, 0.665, 1.41],
      [0.51, 0.71, 1.49],
      [0.555, 0.675, 1.7],
      [0.43, 0.695, 1.87],
    ],
    0.025,
    materials.rubber,
    28,
    10,
  )
  addTube(
    group,
    'radiator-lower-hose',
    [
      [-0.41, 0.43, 1.87],
      [-0.52, 0.405, 1.75],
      [-0.43, 0.39, 1.65],
      [-0.25, 0.47, 1.48],
    ],
    0.023,
    materials.rubber,
    26,
    10,
  )
  for (const [name, x, y, z, radius] of [
    ['upper-engine', 0.27, 0.665, 1.41, 0.028],
    ['upper-radiator', 0.43, 0.695, 1.87, 0.028],
    ['lower-radiator', -0.41, 0.43, 1.87, 0.026],
    ['lower-engine', -0.25, 0.47, 1.48, 0.026],
  ]) {
    addMesh(
      group,
      `radiator-${name}-hose-clamp`,
      new THREE.TorusGeometry(radius, 0.0045, 6, 18),
      materials.clamp,
      [x, y, z],
      [Math.PI / 2, 0, 0],
    )
  }

  const coolant = named(new THREE.Group(), 'coolant-expansion-reservoir')
  coolant.position.set(-0.46, 0.72, 1.3)
  coolant.userData = { component: 'coolant-expansion-reservoir', inspectable: true }
  group.add(coolant)
  const coolantFill = addMesh(
    coolant,
    'coolant-visible-fill',
    new THREE.SphereGeometry(1, 28, 16),
    materials.coolantFluid,
    [0, -0.026, 0],
  )
  coolantFill.scale.set(0.096, 0.068, 0.081)

  const reservoirShell = addMesh(
    coolant,
    'coolant-reservoir-shell',
    new THREE.SphereGeometry(1, 32, 18),
    materials.coolantTank,
    [0, 0, 0],
  )
  reservoirShell.scale.set(0.112, 0.095, 0.096)
  reservoirShell.geometry.userData.form = 'moulded-ellipsoid-reservoir'

  const reservoirSeam = addMesh(
    coolant,
    'coolant-reservoir-equatorial-seam',
    new THREE.TorusGeometry(0.1, 0.0035, 7, 32),
    materials.plasticEdge,
    [0, 0.004, 0],
    [Math.PI / 2, 0, 0],
  )
  reservoirSeam.scale.set(1.08, 0.92, 1)
  const reservoirCradle = addMesh(
    coolant,
    'coolant-reservoir-lower-cradle',
    new THREE.TorusGeometry(0.075, 0.009, 8, 28),
    materials.plasticEdge,
    [0, -0.089, 0],
    [Math.PI / 2, 0, 0],
  )
  reservoirCradle.scale.set(1.12, 0.92, 1)
  addMesh(
    coolant,
    'coolant-reservoir-return-nipple',
    new THREE.CylinderGeometry(0.012, 0.015, 0.052, 14),
    materials.coolantTank,
    [-0.077, 0.035, 0.064],
    [Math.PI / 2, 0, 0],
  )
  for (const [level, y, width] of [['max', 0.032, 0.061], ['min', -0.025, 0.043]]) {
    const mark = addMesh(
      coolant,
      `coolant-${level}-level-mark`,
      roundedBoxGeometry(width, 0.008, 0.006, 0.002),
      materials.plasticEdge,
      [-0.035, y, 0.081],
    )
    mark.userData = { label: level.toUpperCase(), inspectable: true }
  }
  addMesh(
    coolant,
    'coolant-reservoir-filler-neck',
    new THREE.CylinderGeometry(0.04, 0.047, 0.032, 22),
    materials.coolantTank,
    [0.016, 0.118, -0.004],
  )
  addMesh(
    coolant,
    'coolant-reservoir-cap',
    new THREE.CylinderGeometry(0.05, 0.05, 0.035, 24),
    materials.capBlue,
    [0.016, 0.146, -0.004],
  )
  for (let index = 0; index < 10; index += 1) {
    const angle = index * Math.PI * 2 / 10
    addMesh(
      coolant,
      `coolant-cap-grip-rib-${index + 1}`,
      roundedBoxGeometry(0.01, 0.038, 0.025, 0.003),
      materials.capBlue,
      [0.016 + Math.cos(angle) * 0.046, 0.146, -0.004 + Math.sin(angle) * 0.046],
      [0, -angle, 0],
    )
  }
  addTube(
    group,
    'coolant-degas-hose',
    [
      [-0.445, 0.79, 1.34],
      [-0.36, 0.8, 1.4],
      [-0.29, 0.76, 1.52],
    ],
    0.009,
    materials.rubber,
    16,
    8,
  )

  group.traverse((object) => {
    if (!object.isMesh && !object.isInstancedMesh) return
    object.castShadow = true
    object.receiveShadow = true
  })

  return { group, cover, pulleys, fans, coolant, radiator }
}

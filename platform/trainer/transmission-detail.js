import * as THREE from 'three'

const AXLE_Y = 0.315
const AXLE_Z = 1.3157

function outline(points) {
  const shape = new THREE.Shape()
  const last=points.at(-1), first=points[0]
  shape.moveTo(-(last[0]+first[0])/2,(last[1]+first[1])/2)
  for(let index=0;index<points.length;index++) {
    const current=points[index], next=points[(index+1)%points.length]
    shape.quadraticCurveTo(-current[0],current[1],-(current[0]+next[0])/2,(current[1]+next[1])/2)
  }
  shape.closePath()
  return shape
}

function profile(points, width, bevel = 0.003) {
  const shape=outline(points)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: width - bevel * 2, bevelEnabled: true,
    bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: 3,
  })
  geometry.translate(0, 0, -(width - bevel * 2) / 2)
  geometry.rotateY(Math.PI / 2)
  return geometry
}

function taperedCasting(points,width,scales=[.82,.92,1.0,1.02,1.0,.94,.87]) {
  const contour=outline(points).getPoints(3)
  if(contour[0].distanceTo(contour.at(-1))<1e-8) contour.pop()
  if(THREE.ShapeUtils.isClockWise(contour)) contour.reverse()
  const vertices=[],indices=[],uv=[]
  const count=contour.length
  for(let ring=0;ring<scales.length;ring++) {
    const x=(ring/(scales.length-1)-.5)*width
    for(let i=0;i<count;i++) {
      vertices.push(x,contour[i].y*scales[ring],-contour[i].x*scales[ring])
      uv.push(i/count,ring/(scales.length-1))
      if(ring<scales.length-1) {
        const a=ring*count+i,b=ring*count+(i+1)%count,c=a+count,d=b+count
        indices.push(a,b,c,b,d,c)
      }
    }
  }
  const faces=THREE.ShapeUtils.triangulateShape(contour,[])
  for(const ring of [0,scales.length-1]) {
    const base=vertices.length/3
    for(let i=0;i<count;i++) {
      vertices.push((ring/(scales.length-1)-.5)*width,contour[i].y*scales[ring],-contour[i].x*scales[ring])
      uv.push(contour[i].x*3+.5,contour[i].y*3+.5)
    }
    for(const [a,b,c] of faces) indices.push(...(ring===0?[base+c,base+b,base+a]:[base+a,base+b,base+c]))
  }
  const geometry=new THREE.BufferGeometry()
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3))
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  geometry.userData={casting:'smooth-tapered-cross-sections',crossSections:scales.length}
  return geometry
}

function castWebGeometry(start,end,baseX=-.12,peakX=-.141,width=.013) {
  const dy=end[0]-start[0],dz=end[1]-start[1],length=Math.hypot(dy,dz)
  const oy=-dz/length,oz=dy/length
  const vertices=[]
  for(const [y,z] of [start,end]) {
    for(const [x,w] of [[baseX,-width/2],[baseX,width/2],[peakX,-width*.17],[peakX,width*.17]])
      vertices.push(x,y+oy*w,z+oz*w)
  }
  const geometry=new THREE.BufferGeometry()
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3))
  geometry.setIndex([0,2,1,1,2,3,4,5,6,5,7,6,0,4,2,2,4,6,1,3,5,3,7,5,2,6,3,3,6,7,0,1,4,1,5,4])
  geometry.computeVertexNormals()
  return geometry
}

function softBox(w, h, d, bevel = 0.002) {
  const r = Math.min(bevel, w / 5, h / 5, d / 5)
  const shape = new THREE.Shape()
  shape.moveTo(-w / 2 + r, -h / 2 + r)
  shape.lineTo(w / 2 - r, -h / 2 + r)
  shape.lineTo(w / 2 - r, h / 2 - r)
  shape.lineTo(-w / 2 + r, h / 2 - r)
  shape.closePath()
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: d - r * 2, bevelEnabled: true, bevelThickness: r,
    bevelSize: r, bevelSegments: 2, curveSegments: 1,
  })
  geometry.translate(0, 0, -(d - r * 2) / 2)
  return geometry
}

/**
 * A visually reconstructed transverse DSG exterior and front CV shafts.
 * Dimensions/routing are illustrative training geometry, not OEM CAD.
 * World coordinates match the Golf bay: +Y up, +Z towards the nose.
 */
export function buildTransmission({ materialFactory } = {}) {
  if (typeof materialFactory !== 'function') throw new TypeError('buildTransmission requires a materialFactory')
  const makeMaterial = (color, options, finish) => {
    const material = materialFactory(color, options, finish)
    if (!material?.isMaterial) throw new TypeError('materialFactory must return a THREE.Material')
    return material
  }
  const materials = {
    cast: makeMaterial(0x737874, { metalness: 0.58, roughness: 0.73, envMapIntensity: .65 }, 'cast'),
    rib: makeMaterial(0x818680, { metalness: 0.63, roughness: 0.66, envMapIntensity: .65 }, 'cast'),
    recess: makeMaterial(0x555c58, { metalness: 0.52, roughness: 0.79, envMapIntensity: .5 }, 'cast'),
    machined: makeMaterial(0xa6afb5, { metalness: 0.85, roughness: 0.4 }, 'brushed'),
    steel: makeMaterial(0x555b61, { metalness: 0.86, roughness: 0.43 }, 'brushed'),
    black: makeMaterial(0x1e2326, { metalness: 0.12, roughness: 0.63 }, 'plastic'),
    rubber: makeMaterial(0x15181a, { metalness: 0, roughness: 0.86 }, 'rubber'),
    gasket: makeMaterial(0x303235, { metalness: 0, roughness: 0.9 }, 'rubber'),
  }
  const group = new THREE.Group()
  group.name = 'transverse-dsg-transmission'
  group.userData = { provenance: 'constructed-training-geometry', layout: 'transverse-front-wheel-drive', oemVerified: false }
  const components = {}
  const component = (name, label, position = [0, 0, 0]) => {
    const object = new THREE.Group()
    object.name = name
    object.position.set(...position)
    object.userData = { component: name, label, inspectable: true, provenance: 'constructed-training-geometry' }
    components[name] = object
    group.add(object)
    return object
  }
  const mesh = (parent, name, geometry, material, position = [0, 0, 0], rotation = [0, 0, 0]) => {
    const object = new THREE.Mesh(geometry, material)
    object.name = name
    object.position.set(...position)
    object.rotation.set(...rotation)
    object.castShadow = object.receiveShadow = true
    parent.add(object)
    return object
  }
  const boltGeometry = new THREE.CylinderGeometry(0.006, 0.006, 0.007, 6)
  const washerGeometry = new THREE.CylinderGeometry(0.008, 0.008, 0.002, 12)
  const cylinder = (parent, name, radius, length, position, material, radiusBack = radius, segments = 24) =>
    mesh(parent, name, new THREE.CylinderGeometry(radius, radiusBack, length, segments), material, position, [0, 0, Math.PI / 2])
  const bolt = (parent, name, position, axis = 'x') => {
    const rotation = axis === 'x' ? [0, 0, Math.PI / 2] : axis === 'z' ? [Math.PI / 2, 0, 0] : [0, 0, 0]
    mesh(parent, `${name}-washer`, washerGeometry, materials.steel, position, rotation)
    mesh(parent, name, boltGeometry, materials.machined, position, rotation)
  }
  const bar = (parent, name, start, end, radius = 0.004, material = materials.rib) => {
    const a = new THREE.Vector3(...start), b = new THREE.Vector3(...end)
    const object = mesh(parent, name, new THREE.CylinderGeometry(radius, radius, a.distanceTo(b), 7), material)
    object.position.copy(a).add(b).multiplyScalar(0.5)
    object.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.sub(a).normalize())
    return object
  }

  const caseProfile = [[-.13,-.04],[-.141,.003],[-.132,.053],[-.105,.082],[-.069,.09],[-.052,.13],[-.011,.159],[.03,.156],[.065,.137],[.079,.099],[.065,.061],[.048,.037],[.058,-.002],[.077,-.029],[.082,-.071],[.064,-.111],[.027,-.132],[-.021,-.125],[-.047,-.099],[-.076,-.103],[-.116,-.086]]
  const housing = component('gearbox-case', 'DSG cast aluminium gearcase', [-.445, .465, 1.475])
  mesh(housing, 'irregular-gearcase-casting', taperedCasting(caseProfile, .205), materials.cast)
  mesh(housing, 'gearcase-end-cover-gasket', profile(caseProfile.map(([z,y])=>[z*.875,y*.875]), .004, .001), materials.gasket, [-.106,0,0])
  mesh(housing, 'ribbed-end-cover', profile(caseProfile.map(([z,y])=>[z*.90,y*.90]), .023, .004), materials.cast, [-.108,0,0])
  // Circular bearing pockets break up the cover. Raised tapered webs join the
  // bosses into the casting, rather than looking like rods glued to a box.
  const bearings=[['upper',.09,.008,.039],['middle',.012,-.076,.040],['lower',-.069,.023,.040]]
  for(const [name,y,z,radius] of bearings) {
    cylinder(housing,`${name}-bearing-pocket`,radius,.004,[-.121,y,z],materials.recess,radius,32)
    mesh(housing,`${name}-bearing-cast-rim`,new THREE.TorusGeometry(radius,.0045,6,32),materials.rib,[-.126,y,z],[0,Math.PI/2,0])
    cylinder(housing,`${name}-bearing-cap`,radius*.55,.007,[-.127,y,z],materials.cast,radius*.62,24)
    cylinder(housing,`${name}-bearing-center-plug`,radius*.23,.006,[-.134,y,z],materials.steel,radius*.23,6)
    for(let i=0;i<4;i++) {
      const angle=(i/4+.10)*Math.PI*2
      const inner=[y+Math.sin(angle)*radius,z+Math.cos(angle)*radius]
      const outer=[y+Math.sin(angle)*radius*1.40,z+Math.cos(angle)*radius*1.40]
      mesh(housing,`${name}-integral-radial-web-${i+1}`,castWebGeometry(inner,outer),materials.rib)
    }
  }
  const connections=[[[.062,-.013],[.033,-.05]],[[.001,-.045],[-.041,-.004]],[[.053,.028],[-.031,.029]],[[.051,-.061],[.095,-.015]]]
  connections.forEach(([a,b],i)=>mesh(housing,`end-cover-cross-rib-${i+1}`,castWebGeometry(a,b,-.121,-.144,.015),materials.rib))
  for(let i=0;i<5;i++) {
    const x=-.072+i*.034
    const rib=mesh(housing,`upper-casting-web-${i+1}`,profile([[-.095,.075],[-.045,.12],[.012,.144],[.026,.131],[-.039,.103],[-.098,.059]],.009,.002),materials.rib,[x,0,0])
    rib.userData.component='integral-casting-web'
  }
  caseProfile.filter((_,i)=>i%2===0).forEach(([z,y],index)=>bolt(housing, `end-cover-bolt-${index+1}`,[-.122,y*.80,z*.80]))
  cylinder(housing, 'oil-level-plug', .012, .012, [-.136,-.045,-.037], materials.machined, .012, 6)
  cylinder(housing, 'oil-drain-plug', .01, .01, [-.108,-.117,-.025], materials.steel, .01, 6)
  mesh(housing, 'gearcase-identification-plate', softBox(.002,.018,.038,.0005), materials.machined, [-.125,-.017,.047])

  const bellProfile = Array.from({length:20},(_,index)=> {
    const angle = index/20*Math.PI*2
    const radius = .155 * (1 + .05*Math.sin(angle*3) + .025*Math.cos(angle*5))
    return [Math.cos(angle)*radius, Math.sin(angle)*radius]
  })
  const bellhousing = component('bellhousing', 'Dual-clutch bellhousing and engine flange', [-.296,.463,1.484])
  mesh(bellhousing, 'asymmetric-bellhousing-shell', taperedCasting(bellProfile,.083,[.78,.84,.94,1,1.025,1.02]), materials.cast)
  mesh(bellhousing, 'bellhousing-engine-flange', profile(bellProfile.map(([z,y])=>[z*1.05,y*1.05]),.012,.002),materials.machined,[.043,0,0])
  const bellRingGeometry = new THREE.TorusGeometry(.146,.005,6,32)
  mesh(bellhousing, 'bellhousing-machined-register', bellRingGeometry, materials.machined, [.05,0,0], [0,Math.PI/2,0])
  cylinder(bellhousing,'starter-mounting-cast-boss',.068,.042,[-.057,-.018,.116],materials.cast,.055)
  for(let index=0;index<12;index++) {
    const angle=index/12*Math.PI*2
    const z=Math.cos(angle)*.144, y=Math.sin(angle)*.144
    bolt(bellhousing,`engine-flange-bolt-${index+1}`,[.052,y,z])
    mesh(bellhousing,`bellhousing-radial-rib-${index+1}`,castWebGeometry([y*.54,z*.54],[y*.94,z*.94],-.043,-.056,.012),materials.rib)
  }

  const mechatronic = component('mechatronic-cover', 'Mechatronic hydraulic control cover', [-.437,.449,1.329])
  mechatronic.rotation.y=Math.PI
  mesh(mechatronic,'mechatronic-gasket',softBox(.183,.176,.008,.01),materials.gasket,[0,0,-.008])
  mesh(mechatronic,'pressed-mechatronic-cover',softBox(.17,.163,.025,.012),materials.black)
  mesh(mechatronic,'mechatronic-recess',softBox(.132,.122,.004,.008),materials.black,[0,0,.014])
  for(let i=0;i<4;i++) {
    const x=-.069+i*.046
    bolt(mechatronic,`mechatronic-upper-bolt-${i+1}`,[x,.068,.018],'z')
    bolt(mechatronic,`mechatronic-lower-bolt-${i+1}`,[x,-.068,.018],'z')
  }
  for(const side of [-1,1]) bolt(mechatronic,`mechatronic-side-bolt-${side}`,[side*.074,0,.018],'z')
  cylinder(mechatronic,'mechatronic-electrical-socket',.017,.021,[-.084,.057,.003],materials.black)
  cylinder(mechatronic,'mechatronic-socket-lock-ring',.019,.006,[-.098,.057,.003],materials.steel)

  const oilFilter=component('transmission-oil-filter','DSG oil-filter housing',[-.473,.648,1.44])
  mesh(oilFilter,'oil-filter-cast-base',new THREE.CylinderGeometry(.028,.032,.024,24),materials.cast,[0,-.03,0])
  mesh(oilFilter,'oil-filter-black-canister',new THREE.CylinderGeometry(.026,.028,.065,24),materials.black)
  mesh(oilFilter,'oil-filter-cap-seam',new THREE.TorusGeometry(.0265,.002,5,24),materials.gasket,[0,.025,0],[Math.PI/2,0,0])
  mesh(oilFilter,'oil-filter-hex-cap',new THREE.CylinderGeometry(.016,.016,.009,6),materials.black,[0,.036,0])
  for(let index=0;index<12;index++) {
    const a=index/12*Math.PI*2
    bar(oilFilter,`filter-cap-grip-${index+1}`,[Math.sin(a)*.026,-.014,Math.cos(a)*.026],[Math.sin(a)*.026,.023,Math.cos(a)*.026],.0018,materials.black)
  }

  const cooler=component('transmission-oil-cooler','Stacked-plate transmission oil cooler',[-.354,.631,1.464])
  const plate=softBox(.091,.003,.097,.001)
  for(let index=0;index<12;index++) mesh(cooler,`oil-cooler-plate-${index+1}`,plate,materials.machined,[0,index*.004,0])
  mesh(cooler,'oil-cooler-top-plate',softBox(.093,.008,.098,.003),materials.cast,[0,.047,0])
  for(const side of [-1,1]) {
    mesh(cooler,`cooler-coolant-neck-${side}`,new THREE.CylinderGeometry(.010,.010,.031,16),materials.machined,[side*.026,.066,.014])
    mesh(cooler,`cooler-hose-collar-${side}`,new THREE.TorusGeometry(.0105,.0018,5,16),materials.steel,[side*.026,.076,.014],[Math.PI/2,0,0])
  }

  const differential=component('integrated-front-differential','Integrated front differential housing',[-.43,AXLE_Y+.013,AXLE_Z+.024])
  cylinder(differential,'integrated-differential-casting',.073,.252,[0,0,0],materials.cast,.062,28)
  for(let i=0;i<4;i++) {
    const ring=new THREE.TorusGeometry(.070-i*.002,.0035,5,24)
    mesh(differential,`differential-casting-rib-${i+1}`,ring,materials.rib,[-.09+i*.055,0,0],[0,Math.PI/2,0])
  }

  const shafts=[]
  function cvBoot(parent,name,x,radius,length,direction=1) {
    const points=[new THREE.Vector2(radius*.46,-length/2)]
    for(let index=0;index<=12;index++) {
      const t=index/12
      const envelope=.60+.40*Math.sin(t*Math.PI)
      const r=radius*envelope*(index%2===0?.71:1)
      points.push(new THREE.Vector2(r,(t-.5)*length))
    }
    points.push(new THREE.Vector2(radius*.43,length/2))
    const boot=mesh(parent,name,new THREE.LatheGeometry(points,20),materials.rubber,[x,0,0],[0,0,direction*Math.PI/2])
    for(const side of [-1,1]) cylinder(parent,`${name}-band-${side}`,radius*.46,.006,[x+side*length/2,0,0],materials.machined)
    return boot
  }
  for(const [side,innerX,outerX] of [['left',-.575,-.764],['right',-.276,.764]]) {
    const direction=Math.sign(outerX-innerX)
    const output=component(`cv-output-${side}`,`${side==='left'?'Short':'Long'}-side CV output flange`,[innerX,AXLE_Y,AXLE_Z])
    cylinder(output,`${side}-output-flange`,.039,.022,[0,0,0],materials.steel)
    cylinder(output,`${side}-output-register`,.026,.027,[direction*.012,0,0],materials.machined)
    for(let i=0;i<6;i++) {
      const angle=i/6*Math.PI*2
      bolt(output,`${side}-cv-flange-bolt-${i+1}`,[direction*.014,Math.sin(angle)*.031,Math.cos(angle)*.031])
    }
    const shaft=component(`driveshaft-${side}`,`${side==='left'?'Short':'Long'} front driveshaft and CV joints`,[0,AXLE_Y,AXLE_Z])
    shaft.userData.rotationAxis='x'
    shaft.userData.innerMountX=innerX
    shaft.userData.hubX=outerX
    const innerBootX=innerX+direction*.048
    const outerBootX=outerX-direction*.036
    cvBoot(shaft,`${side}-inner-cv-accordion-boot`,innerBootX,.032,.059,direction)
    cvBoot(shaft,`${side}-outer-cv-accordion-boot`,outerBootX,.035,.054,-direction)
    const rodStart=innerBootX+direction*.031
    const rodEnd=outerBootX-direction*.029
    cylinder(shaft,`${side}-forged-drive-shaft`,.012,Math.abs(rodEnd-rodStart),[(rodStart+rodEnd)/2,0,0],materials.steel)
    cylinder(shaft,`${side}-hub-cv-body`,.027,.028,[outerX-direction*.009,0,0],materials.steel)
    cylinder(shaft,`${side}-hub-spline`,.015,.030,[outerX+direction*.009,0,0],materials.machined)
    if(side==='right') cylinder(shaft,'long-shaft-vibration-damper',.023,.066,[.17,0,0],materials.rubber)
    shafts.push(shaft)
  }
  group.updateMatrixWorld(true)
  let triangleCount=0
  group.traverse(object=>{
    if(object.isMesh) triangleCount+=(object.geometry.index?.count??object.geometry.attributes.position.count)/3
  })
  group.userData.triangleCount=triangleCount
  return { group, components, shafts }
}

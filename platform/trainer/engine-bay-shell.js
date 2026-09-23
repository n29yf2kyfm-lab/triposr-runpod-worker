import * as THREE from 'three';

// Reconstructed inner pressings, not a measured body-in-white. Curved aprons
// and hollow strut towers replace the previous vertical rectangular walls.
export function buildInnerApron(side, materialFactory) {
  const group=new THREE.Group(); group.name=`inner-apron-${side}`;
  const paint=materialFactory(0x60151b,{roughness:.49,metalness:.18},'paint');
  const seam=materialFactory(0x211a1c,{roughness:.86},'rubber');
  const metal=materialFactory(0x8a9095,{roughness:.44,metalness:.8},'brushed');
  const add=(geometry,material,name,x=0,y=0,z=0)=>{
    const mesh=new THREE.Mesh(geometry,material);mesh.name=name;
    mesh.position.set(side*x,y,z);mesh.castShadow=mesh.receiveShadow=true;group.add(mesh);return mesh;
  };
  const points=[],indices=[],uv=[];
  const sections=30, bands=8;
  for(let j=0;j<=sections;j++){
    const t=j/sections,z=1.12+t*.87;
    const top=.81-.15*t+.025*Math.sin(t*Math.PI);
    for(let k=0;k<=bands;k++){
      const q=k/bands;
      const x=.70-.15*Math.sin(q*Math.PI/2);
      const y=top-.21*q;
      points.push(side*x,y,z);uv.push(t,q);
      if(j<sections&&k<bands){
        const a=j*(bands+1)+k,b=a+bands+1;
        indices.push(a,b,a+1,b,b+1,a+1);
      }
    }
  }
  const sheet=new THREE.BufferGeometry();
  sheet.setAttribute('position',new THREE.Float32BufferAttribute(points,3));
  sheet.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
  sheet.setIndex(indices);sheet.computeVertexNormals();
  paint.side=THREE.DoubleSide;add(sheet,paint,'curved-inner-wing-pressing');
  const tower=new THREE.LatheGeometry([
    [.14,.69],[.142,.73],[.13,.79],[.11,.84],[.085,.882],
    [.050,.889],[.049,.882],[.078,.872],[.103,.83],[.12,.77],[.13,.70],
  ].map(([r,y])=>new THREE.Vector2(r,y)),40);
  add(tower,paint,'hollow-strut-tower',.602,0,1.278);
  const flange=new THREE.TorusGeometry(.081,.006,8,36);
  add(flange,seam,'strut-mount-seam',.602,.881,1.278).rotation.x=Math.PI/2;
  for(let n=0;n<3;n++){
    const angle=n*Math.PI*2/3;
    add(new THREE.CylinderGeometry(.009,.009,.011,6),metal,`tower-fastener-${n}`,
      .602+Math.cos(angle)*.076,.892,1.278+Math.sin(angle)*.076);
  }
  for(const t of [.1,.45,.76]){
    const z=1.12+t*.87,top=.81-.15*t+.025*Math.sin(t*Math.PI);
    add(new THREE.CylinderGeometry(.006,.006,.006,12),metal,`apron-fastener-${t}`,.688,top+.005,z);
  }
  return group;
}

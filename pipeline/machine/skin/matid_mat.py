#!/usr/bin/env python3
"""matid_mat.py -- one flat emissive colour per MATERIAL (not per node).

trimesh's node names for a multi-primitive GLB carry a per-load hash suffix
(Body_Shell_529452 on one load, Body_Shell_cd1a53 on the next), so a legend
keyed on node names cannot be joined to a second load.  Materials are stable.
Written as a direct glTF JSON edit so no geometry passes through trimesh.
"""
import json, struct, sys, colorsys
raw=open(sys.argv[1],'rb').read(); p=12
jl,_=struct.unpack('<II',raw[p:p+8]); p+=8; gl=json.loads(raw[p:p+jl]); p+=jl
bl,_=struct.unpack('<II',raw[p:p+8]); p+=8; BIN=raw[p:p+bl]
leg={}
for i,m in enumerate(gl['materials']):
    r,g,b=colorsys.hsv_to_rgb((i*0.3819)%1.0, 0.6+0.4*((i%3)/2), 1.0)
    leg[m['name']]=[round(r,4),round(g,4),round(b,4)]
    m['pbrMetallicRoughness']={'baseColorFactor':[0,0,0,1],'metallicFactor':0.0,'roughnessFactor':1.0}
    m['emissiveFactor']=[r,g,b]
    m.pop('extensions',None); m['alphaMode']='OPAQUE'; m['doubleSided']=True
jb=json.dumps(gl,separators=(',',':')).encode()
while len(jb)%4: jb+=b' '
open(sys.argv[2],'wb').write(struct.pack('<III',0x46546C67,2,12+8+len(jb)+8+len(BIN))+struct.pack('<II',len(jb),0x4E4F534A)+jb+struct.pack('<II',len(BIN),0x004E4942)+BIN)
json.dump(leg,open(sys.argv[2]+'.legend.json','w'),indent=1)
print('[matid_mat]',sys.argv[2],len(leg),'materials')

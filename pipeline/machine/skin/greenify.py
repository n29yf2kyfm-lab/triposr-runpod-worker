#!/usr/bin/env python3
"""greenify.py -- recolour the dark shell materials to saturated hues so the
label partition is legible in a normally-lit render.  Pure JSON edit, BIN kept.
"""
import json,struct,sys
COL={'Interior_Plastic':[0,1,0,1],'Arch_Liner':[0,0.4,1,1],'Underbody':[1,0.6,0,1],'Trim_Black':[1,1,0,1]}
raw=open(sys.argv[1],'rb').read(); p=12
jl,_=struct.unpack('<II',raw[p:p+8]); p+=8; gl=json.loads(raw[p:p+jl]); p+=jl
bl,_=struct.unpack('<II',raw[p:p+8]); p+=8; BIN=raw[p:p+bl]
for m in gl['materials']:
    if m['name'] in COL:
        pbr=m.setdefault('pbrMetallicRoughness',{})
        pbr['baseColorFactor']=COL[m['name']]; pbr['roughnessFactor']=0.6; pbr['metallicFactor']=0.0
jb=json.dumps(gl,separators=(',',':')).encode()
while len(jb)%4: jb+=b' '
open(sys.argv[2],'wb').write(struct.pack('<III',0x46546C67,2,12+8+len(jb)+8+len(BIN))+struct.pack('<II',len(jb),0x4E4F534A)+jb+struct.pack('<II',len(BIN),0x004E4942)+BIN)
print("wrote",sys.argv[2])

import json, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import glb_parts as G
SP=sys.argv[1]
rows=json.load(open(f'{SP}/parts_audit.json'))
cat=json.loads(G.fetch(G.CATALOGUE)[0].decode()); byid={x['assetId']:x for x in cat}
key=lambda r:(r['meshes'],r['materials'],r['nodes'],r['named'],tuple(sorted(r['groups'].items())))
g=defaultdict(list)
for r in rows:
    if 'error' not in r: g[key(r)].append(r)
cand=[v for v in g.values() if len(v)>1]
ids=sorted({r['assetId'] for v in cand for r in v})
def bbox(aid):
    try:
        gj,_=G.glb_json(byid[aid]['desktopGlbUrl']); acc=gj.get('accessors',[])
        lo=[1e9]*3; hi=[-1e9]*3
        for m in gj.get('meshes',[]):
            for p in m.get('primitives',[]):
                i=p.get('attributes',{}).get('POSITION')
                if i is None: continue
                a=acc[i]
                if 'min' not in a: continue
                for k in range(3): lo[k]=min(lo[k],a['min'][k]); hi[k]=max(hi[k],a['max'][k])
        return aid, tuple(round(hi[k]-lo[k],4) for k in range(3))
    except Exception as e:
        return aid, ('ERR',str(e)[:30],'')
print(f'{len(cand)} fingerprint groups, {len(ids)} assets to measure', flush=True)
ex={}
with ThreadPoolExecutor(max_workers=4) as p:
    for aid,b in p.map(bbox, ids): ex[aid]=b
out=[]
for v in cand:
    sub=defaultdict(list)
    for r in v: sub[ex[r['assetId']]].append(r)
    for box,members in sub.items():
        if len(members)>1 and 'ERR' not in str(box):
            makes={m['make'] for m in members}; models={m['model'] for m in members}
            out.append({'box':list(box),'meshes':members[0]['meshes'],
                        'crossMake':len(makes)>1,'crossModel':len(models)>1,
                        'assets':[{'assetId':m['assetId'],'make':m['make'],'model':m['model'],
                                   'title':m.get('sourceTitle'),
                                   'sourceRef':byid[m['assetId']].get('sourceReferenceId')}
                                  for m in members]})
out.sort(key=lambda d:(-d['crossMake'],-d['meshes']))
json.dump(out, open('duplicate_meshes.json','w'), indent=1)
cm=[d for d in out if d['crossMake']]; cmo=[d for d in out if d['crossModel'] and not d['crossMake']]
same=[d for d in out if not d['crossModel']]
print(f"\nCONFIRMED identical geometry: {len(out)} groups")
print(f"  {len(cm)} span DIFFERENT MAKES   <-- wrong car served")
print(f"  {len(cmo)} span different models, same make")
print(f"  {len(same)} are duplicate entries for the SAME model (benign)")
for d in cm:
    print(f"\n  {d['meshes']} meshes  extents {d['box']}")
    for a in d['assets']: print(f"      {a['assetId']:<44} {a['make']}/{a['model']}  {str(a['title'])[:28]}")

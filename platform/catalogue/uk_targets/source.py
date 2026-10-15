"""Anonymous Sketchfab candidate search for every target in targets.csv.
No download (needs tokens). Commercial-OK licences only: by, by-sa, cc0."""
import csv, json, time, re, sys, urllib.request, urllib.parse, urllib.error
OK={'322a749bcfa841b29dff1e8a1bb74b0b':'by','b9ddc40b93e34cdca1fc152f39b9f375':'by-sa','7c23a1ba438d4306920229c12afcb5f9':'cc0'}
HINT={'car':'','van':' van','truck':' truck','motorbike':' motorcycle','bus':' bus'}
PANEL=re.compile(r'interior|door|open|animated|rigged|engine|detailed|hinge', re.I)
def get(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'ecc-sourcing/1.0'}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==429 or e.code>=500: time.sleep(2**i*2); continue
            return None
        except Exception: time.sleep(2**i); 
    return None
def q(text):
    p=urllib.parse.urlencode({'type':'models','q':text,'downloadable':'true','count':24,'sort_by':'-likeCount'})
    d=get('https://api.sketchfab.com/v3/search?'+p); return (d or {}).get('results') or []
def cand(r, target_words):
    lic=(r.get('license') or {}).get('uid'); 
    if lic not in OK: return None
    name=r.get('name') or ''; nm=name.lower()
    hit=sum(w in nm for w in target_words)
    if hit==0: return None
    glb=(r.get('archives') or {}).get('glb') or {}
    text=' '.join([name, r.get('description') or '', ' '.join(t.get('name','') for t in r.get('tags') or [])])
    return {'uid':r['uid'],'name':name,'licence':OK[lic],'faces':r.get('faceCount'),'verts':r.get('vertexCount'),
            'anim':r.get('animationCount'),'glbMB':round((glb.get('size') or 0)/1e6,1),'tex':glb.get('textureCount'),
            'likes':r.get('likeCount'),'views':r.get('viewCount'),'user':(r.get('user') or {}).get('username'),
            'panel_words':sorted(set(m.group(0).lower() for m in PANEL.finditer(text))),'name_hits':hit,
            'thumb':next((t['url'] for t in sorted(((r.get('thumbnails') or {}).get('images') or []), key=lambda t:-t.get('width',0)) if t.get('width',0)<=720), None),
            'url':r.get('viewerUrl')}
rows=list(csv.DictReader(open('targets.csv')))
order={'none':0,'refused':1,'partial':2,'ok':3}
rows.sort(key=lambda r:(order[r['rig']], r['class']!='car', int(r['rank'])))
done=set()
try:
    for l in open('candidates.jsonl'): done.add(json.loads(l)['key'])
except FileNotFoundError: pass
out=open('candidates.jsonl','a'); t0=time.time()
for i,r in enumerate(rows):
    key=f"{r['class']}|{r['make']}|{r['genModel']}"
    if key in done: continue
    make=r['make'].replace(' TRUCKS','').title(); model=r['genModel'].replace(r['make'],'',1).strip().title()
    words=[w.lower() for w in model.split() if len(w)>1] or [model.lower()]
    seen={}; 
    for text in (f"{make} {model}{HINT[r['class']]}", f"{make} {model}"):
        for x in q(text):
            c=cand(x, words)
            if c and c['uid'] not in seen: seen[c['uid']]=c
        time.sleep(0.7)
        if len(seen)>=6 and r['class']=='car': break
    cs=sorted(seen.values(), key=lambda c:(-c['name_hits'], -(c['likes'] or 0)))[:8]
    out.write(json.dumps({'key':key,'class':r['class'],'rank':int(r['rank']),'make':r['make'],'genModel':r['genModel'],'licensed':int(r['licensed']),
                          'rig':r['rig'],'have':int(r['assets']),'n':len(cs),'candidates':cs})+'\n'); out.flush()
    if i%25==0: print(f"{i}/{len(rows)} {key} -> {len(cs)}  {time.time()-t0:.0f}s", flush=True)
print('DONE', flush=True)

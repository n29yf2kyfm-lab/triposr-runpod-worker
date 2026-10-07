import json,re,sys
def state(body):
    m=re.search(r'```json\s*(\[\["ShallowReactive".*?)```',body,re.S)
    return json.loads(m.group(1))
def resolve(a,i,depth=0):
    v=a[i]
    if depth>6: return v
    if isinstance(v,dict): return {k:resolve(a,x,depth+1) if isinstance(x,int) else x for k,x in v.items()}
    if isinstance(v,list):
        if v and isinstance(v[0],str) and v[0] in('ShallowReactive','Reactive','Ref','ShallowRef'): return resolve(a,v[1],depth+1)
        return [resolve(a,x,depth+1) if isinstance(x,int) else x for x in v]
    return v
def gens(path):
    j=json.load(open(path)); a=state(j['body'])
    out={}
    for i,v in enumerate(a):
        if isinstance(v,dict) and {'code','name','series','region','years','vehicle_type'}<=set(v):
            g=resolve(a,i)
            out[g['code']]=g
    links={}
    for m in re.finditer(r'\]\((https://7zap\.com/en/catalog/[a-z]+/[a-z-]+/[a-z0-9-]+-parts-catalog/)[^ )]* "([^"]+?) — OEM',j['body']):
        links[m.group(2)]=m.group(1)
    for g in out.values():
        g['_links']=links
    return list(out.values())
if __name__=='__main__':
    g=gens(sys.argv[1]); print(len(g)); print(json.dumps(g[:2],indent=1)[:1500])

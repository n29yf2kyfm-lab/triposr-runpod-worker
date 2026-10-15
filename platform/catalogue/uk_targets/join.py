import json, re, csv, collections
R=json.load(open('ranked_by_body.json'))
cars=json.load(open('../catalogue.v2.json'))
surv={json.loads(l)['assetId']:json.loads(l) for l in open('../../rigmachine/survey/survey.jsonl')}
MK={'MERCEDES':'mercedes-benz','VAUXHALL':'vauxhall','LAND ROVER':'land-rover','ALFA ROMEO':'alfa-romeo','ASTON MARTIN':'aston-martin','ROLLS ROYCE':'rolls-royce','DS':'ds','MG':'mg','MINI':'mini','SMART':'smart','ABARTH':'abarth','ISUZU TRUCKS':'isuzu','DAF TRUCKS':'daf','MERCEDES BENZ':'mercedes-benz','VOLKSWAGEN':'volkswagen','JAGUAR':'jaguar','BMW':'bmw','CUPRA':'cupra','LEXUS':'lexus','TESLA':'tesla','POLESTAR':'polestar','GENESIS':'genesis','BYD':'byd','OPEL':'opel'}
n=lambda s: re.sub(r'[^a-z0-9]','',(s or '').lower())
# catalogue index: (make, modelfamily-ish tokens)
cat=collections.defaultdict(list)
for c in cars:
    if c.get('publicationStatus')!='approved': continue
    mk=n(c['make']); mk={'mercedes':'mercedesbenz','vw':'volkswagen'}.get(mk,mk)
    fam=n(c.get('modelFamily') or c.get('model')); fam=fam.replace(mk,'',1) if fam.startswith(mk) else fam
    for alias in set([n(c.get('model')), fam]+[n(a) for a in c.get('modelAliases') or []]):
        if alias: cat[(mk,alias)].append(c)
def find(make, gen):
    mk=n(MK.get(make, make)); g=n(gen); g=g.replace(n(make),'',1) if g.startswith(n(make)) else g
    hits=cat.get((mk,g)) or []
    if not hits:  # prefix match: 'transitcustom' vs 'transit', '3series' vs '320'
        for (m,a),v in cat.items():
            if m==mk and (a.startswith(g) or g.startswith(a)) and min(len(a),len(g))>=3: hits+=v
    seen=set(); out=[]
    for h in hits:
        if h['assetId'] not in seen: seen.add(h['assetId']); out.append(h)
    return out
BODY={'Cars':('car',99),'Light goods vehicles':('van',99),'Heavy goods vehicles':('truck',95),'Motorcycles':('motorbike',95),'Buses and coaches':('bus',80)}
rows=[]; summary={}
for body,(cls,pct) in BODY.items():
    if body not in R: continue
    lst=R[body]; T=R.get('_totals',{}).get(body) or sum(x['licensed'] for x in lst); cum=0; have=0; opens=0; clean=0; k=0
    for i,x in enumerate(lst,1):
        cum+=x['licensed']; 
        if cum-x['licensed'] >= T*pct/100: break
        k=i
        assets=find(x['make'],x['genModel'])
        st=[surv.get(a['assetId'],{}).get('status') for a in assets]
        best='ok' if 'ok' in st else 'partial' if 'partial' in st else ('refused' if assets else 'none')
        lic_ok=any('NonCommercial' not in str(a.get('licence')) for a in assets)
        have+=bool(assets); opens+=best in('ok','partial'); clean+=lic_ok
        rows.append({'class':cls,'rank':i,'make':x['make'],'genModel':x['genModel'],'licensed':x['licensed'],'cum_pct':round(cum*100/T,2),
                     'assets':len(assets),'assetIds':'|'.join(a['assetId'] for a in assets[:6]),'rig':best,'licence_clean':lic_ok})
    summary[cls]={'targets':k,'pct':pct,'have_model':have,'opens_today':opens,'licence_clean':clean}
w=csv.DictWriter(open('targets.csv','w',newline=''),fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(json.dumps(summary,indent=1)); print('total targets', len(rows))

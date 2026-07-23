#!/usr/bin/env python3
"""enrich_spec.py — fill resolver spec (year/fuel/trim) on approved assets.

The resolver scores make/model/generation/year/bodyStyle/fuel/trim, but the
catalogue only reliably carried make/model/body — so year/fuel/trim scoring was
largely dead and the strict threshold had to be dropped to 40. This backfills
yearStart/yearEnd, compatibleFuelTypes and compatibleTrimFamilies from the
curated UK master (build_index.py) plus a supplement of verifiable production
spans + powertrain below. Fill-missing only (never clobbers existing curated
values); generation is deliberately NOT invented. Pass --apply to write.
"""
import json,os,sys
src=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'build_index.py')).read().split('# ---- join')[0]
g={'os':os,'json':json,'urllib':__import__('urllib.request')}; os.environ.setdefault('SB_KEY','x'); exec(src,g)
MASTER=g['index']; TRIM=g['TRIM']
def nkey(s): return (s or '').strip().lower().replace(' ','').replace('-','').replace('+','')
MK_ALIAS={'mercedes':'mercedes-benz','vw':'volkswagen'}
def mkey(s):
    s=(s or '').strip().lower(); s=MK_ALIAS.get(s,s); return s.replace(' ','').replace('-','')
P=['petrol'];D=['diesel'];PD=['petrol','diesel'];PH=['petrol','hybrid'];PDH=['petrol','diesel','hybrid']
E=['electric'];PE=['petrol','electric'];HE=['hybrid','electric'];H=['hybrid'];PHE=['petrol','hybrid','electric']
PDHE=['petrol','diesel','hybrid','electric'];DE=['diesel','electric'];PDE=['petrol','diesel','electric']
# (model, year_from, year_to, fuels) — verifiable UK production spans + powertrain
SUPP={
'alfa-romeo':[('147',2000,2010,PD),('8c',2007,2010,P),('tonale',2022,2026,PH),('brera',2005,2010,PD),('giulietta',2010,2020,PD),('milano',2024,2026,PHE),('mito',2008,2018,P),('stelvio',2017,2026,PDH)],
'alpine':[('a110',2017,2026,P)],'alpina':[('b7',2015,2023,P)],
'audi':[('s3',2015,2026,P),('e-tron',2019,2023,E),('a2',1999,2005,PD),('a7',2010,2026,PDH),('a8',2010,2026,PDH),('e-tron gt',2021,2026,E),('q4 e-tron',2021,2026,E),('r8',2007,2024,P),('rs4',2012,2026,P),('rs6',2013,2026,PH),('rs7',2013,2026,PH),('rsq3',2019,2026,P),('s5',2016,2026,P)],
'aston-martin':[('dbs',2018,2023,P),('dbx',2020,2026,P),('vantage',2018,2026,P)],
'bentley':[('bentayga',2015,2026,PH),('continental',2003,2026,P)],
'bmw':[('7 series',2015,2026,PDHE),('8-series',2018,2026,PD),('m3 e30',1986,1991,P),('m3 e46',2000,2006,P),('xm',2022,2026,PH),('z4',2002,2026,P),('i3',2013,2022,E),('m2',2015,2026,P),('m3',2014,2026,P),('m4',2014,2026,P),('m5',2011,2026,PH),('m6',2012,2018,P),('m8',2019,2026,P),('x2',2018,2026,PDE),('x4',2014,2026,PD),('x6',2008,2026,PD),('x7',2019,2026,PD)],
'byd':[('atto 3',2022,2026,E),('dolphin',2023,2026,E),('seal',2023,2026,E)],
'chevrolet':[('corvette',1997,2026,P)],
'citroen':[('c1',2005,2022,P),('ds3',2009,2019,PD),('e-c3',2024,2026,E)],
'cupra':[('terramar',2024,2026,PH),('tavascan',2024,2026,E),('ateca',2018,2026,P)],
'dacia':[('logan',2004,2026,PD)],
'ferrari':[('308',1975,1985,P),('812',2017,2026,P),('f8',2019,2023,P),('purosangue',2023,2026,P),('roma',2020,2026,P),('sf90',2019,2026,PH)],
'fiat':[('124 spider',2016,2020,P),('punto',1993,2018,PD)],
'ford':[('cortina',1962,1982,P),('escort',1968,2000,PD),('s-max',2006,2023,PD)],
'honda':[('s2000',1999,2009,P),('accord',1998,2015,PD),('insight',2009,2014,H),('nsx',1990,2022,PH),('zr-v',2023,2026,H)],
'hyundai':[('elantra',2000,2026,P),('ioniq-6',2022,2026,E),('ix35',2010,2015,PD)],
'jaguar':[('e-type',1961,1975,P),('f-type',2013,2024,P),('xk',1996,2015,P)],
'jeep':[('grand cherokee',1992,2026,PDH),('compass',2017,2026,PH),('renegade',2014,2026,PH),('wrangler',2007,2026,PH)],
'kia':[('ev3',2024,2026,E),('ev9',2023,2026,E),('optima',2000,2020,PDH),('soul',2008,2026,PE),('stinger',2017,2023,PD),('stonic',2017,2026,PH)],
'lamborghini':[('urus',2018,2026,P)],
'lexus':[('ct',2011,2022,H),('es',2018,2026,H),('lc',2017,2026,PH),('rc',2015,2026,PH),('rx',2003,2026,H),('ux',2018,2026,HE)],
'lotus':[('emeya',2024,2026,E),('emira',2022,2026,P)],
'maserati':[('levante',2016,2026,PDH)],
'mazda':[('6',2002,2024,PD),('rx-7',1978,2002,P),('rx-8',2003,2012,P)],
'mclaren':[('artura',2021,2026,PH)],
'mercedes-benz':[('amg gt',2014,2026,PE),('cla',2013,2026,PDH),('cls',2004,2023,PDH),('g-class',1979,2026,PDE),('gle',2015,2026,PDH),('gls',2015,2026,PDH),('s-class',1972,2026,PDHE),('sl',1954,2026,P),('v-class',2014,2026,DE),('eqe',2022,2026,E)],
'mg':[('cyberster',2024,2026,E)],
'mini':[('clubman',2007,2024,PD),('convertible',2004,2026,P)],
'mitsubishi':[('lancer evolution',1992,2016,P),('mirage',2012,2026,P),('asx',2010,2026,PH),('eclipse-cross',2017,2026,PH),('l200',2006,2024,D)],
'nissan':[('350z',2002,2009,P),('elgrand',1997,2020,PD),('gt-r',2007,2026,P),('note',2004,2022,PH),('nv200',2009,2026,DE),('pulsar',2014,2018,PD)],
'peugeot':[('206',1998,2012,PD),('205',1983,1998,PD),('307',2001,2008,PD),('508',2010,2026,PDH),('e-208',2019,2026,E)],
'porsche':[('718 boxster',2016,2026,PE),('718-cayman',2016,2026,PE),('918-spyder',2013,2015,PH),('carrera-gt',2003,2007,P),('panamera',2009,2026,PH)],
'renault':[('koleos',2007,2026,PD),('arkana',2019,2026,PH),('kadjar',2015,2022,PD),('scenic',1996,2026,PDHE)],
'rolls-royce':[('cullinan',2018,2026,P),('ghost',2009,2026,P)],
'seat':[('tarraco',2018,2026,PDH),('mii',2011,2021,PE)],
'skoda':[('kodiaq',2016,2026,PDH),('rapid',2012,2019,PD),('scala',2019,2026,P)],
'smart':[('fortwo',1998,2024,PE)],
'ssangyong':[('tivoli',2015,2026,PD)],
'subaru':[('legacy',1989,2020,PD),('brz',2012,2026,P),('forester',1997,2026,PH),('outback',1994,2026,PD),('impreza',1992,2026,PH),('wrx',1992,2026,P),('xv',2011,2023,PH)],
'suzuki':[('across',2020,2026,PH),('alto',2009,2014,P),('baleno',2016,2020,P),('jimny',1998,2026,P),('sx4',2006,2026,PD),('swace',2020,2026,H)],
'toyota':[('gr86',2021,2026,P),('highlander',2020,2026,H),('supra',1978,2026,P),('vellfire',2008,2026,H),('bz4x',2022,2026,E),('camry',1982,2026,H),('gt86',2012,2020,P),('land cruiser',1985,2026,D)],
'vauxhall':[('insignia',2008,2022,PD),('zafira',1999,2019,PD)],
'volkswagen':[('amarok',2010,2026,PD),('beetle',1997,2019,PD),('id buzz',2022,2026,E),('multivan',2003,2026,PDH),('id5',2021,2026,E),('jetta',1979,2019,PD),('scirocco',2008,2017,PD),('taigo',2021,2026,P),('touareg',2002,2026,PDH)],
'volvo':[('v40',1995,2019,PD),('v70',1996,2016,PD),('c30',2006,2013,PD),('c40',2021,2026,E),('s60',2000,2026,PDH),('v90',2016,2026,PDH)],
}
# master rows grouped by normalised make
by_make={}
for r in MASTER: by_make.setdefault(mkey(r['make']),[]).append(('m',r['model'],r['year_from'],r['year_to'],r['fuel'],r['make']))
for mk,rows in SUPP.items():
    for (model,yf,yt,fu) in rows: by_make.setdefault(mkey(mk),[]).append(('s',model,yf,yt,fu,mk))

def trims_for(make):
    return TRIM.get(mkey(make).replace('mercedesbenz','mercedes-benz'), TRIM.get((make or '').strip().lower(), []))

def candidates(make,model,gen,aliases):
    rows=by_make.get(mkey(make),[]); keys={nkey(model)}|{nkey(a) for a in (aliases or [])}; gk=nkey(gen)
    # exact model / alias
    ex=[r for r in rows if nkey(r[1]) in keys]
    if ex: return ex
    # longest-prefix variant
    best=[]
    for r in rows:
        rk=nkey(r[1])
        if len(rk)>=2 and any(k.startswith(rk) or rk.startswith(k) for k in keys): best.append(r)
    if best:
        L=max(len(nkey(r[1])) for r in best); best=[r for r in best if len(nkey(r[1]))==L]
    return best

CAT=os.environ.get('CATALOGUE') or os.path.join(os.path.dirname(os.path.abspath(__file__)),'catalogue.v2.json'); cat=json.load(open(CAT)); apply='--apply' in sys.argv
fy=ff=ft=nm=0
for e in cat:
    if e.get('publicationStatus')!='approved': continue
    c=candidates(e.get('make'),e.get('model'),e.get('generation'),e.get('modelAliases'))
    if not c: nm+=1; continue
    yf=min(r[2] for r in c); yt=max(r[3] for r in c); fuels=sorted({x for r in c for x in r[4]})
    trims=sorted(set(trims_for(e.get('make'))))
    if e.get('yearStart') is None: e['yearStart']=yf; fy+=1
    if e.get('yearEnd') is None: e['yearEnd']=yt
    if not e.get('compatibleFuelTypes') and fuels: e['compatibleFuelTypes']=fuels; ff+=1
    if not e.get('compatibleTrimFamilies') and trims: e['compatibleTrimFamilies']=trims; ft+=1
if apply: json.dump(cat,open(CAT,'w'),indent=1,ensure_ascii=False)
ap=[e for e in cat if e.get('publicationStatus')=='approved']
def cov(p): return sum(1 for e in ap if p(e))
print(f"{'APPLIED' if apply else 'DRY'}: newly filled year={fy} fuel={ff} trim={ft} | still-unmatched={nm}")
print("coverage: year",cov(lambda e:e.get('yearStart') is not None),
      "fuel",cov(lambda e:e.get('compatibleFuelTypes')),
      "trim",cov(lambda e:e.get('compatibleTrimFamilies')),"/",len(ap))

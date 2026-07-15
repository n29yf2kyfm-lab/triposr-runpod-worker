"""UK vehicle master index 2015-2026 (cars, vans, motorbikes).
Indexed on class/make/model/generation/year_from/year_to/body/fuel/trims/colours.
Curated representative dataset (major UK market). has_3d joined from catalogue.json.
Stored to Supabase car-renders/vehicle_index.json.
"""
import os, json, urllib.request, urllib.error

REF="tfkvthprsntexrcuqpyd"; SBKEY=os.environ["SB_KEY"]
BASE=f"https://{REF}.supabase.co/storage/v1/object"; PUB=f"{BASE}/public/car-renders"

# DVLA colour vocabulary (applies to all vehicles)
COLOURS=sorted(["Black","White","Silver","Grey","Blue","Red","Green","Bronze",
                "Orange","Yellow","Purple","Brown","Gold","Beige","Maroon",
                "Pink","Turquoise"])

P,D,H,E=["petrol"],["diesel"],["hybrid"],["electric"]
PD=["petrol","diesel"]; PDH=["petrol","diesel","hybrid"]; PHE=["petrol","hybrid","electric"]
PH=["petrol","hybrid"]; ALL=["petrol","diesel","hybrid","electric"]
PE=["petrol","electric"]; PDE=["petrol","diesel","electric"]; DE=["diesel","electric"]

# trim ladders by brand (real UK trim names, representative)
TRIM={
 "audi":["SE","Sport","S line","Black Edition","Vorsprung","S","RS"],
 "bmw":["SE","Sport","M Sport","M Sport Pro","M"],
 "mercedes-benz":["SE","Sport","AMG Line","AMG Line Premium","AMG"],
 "volkswagen":["S","SE","SE L","R-Line","GTI","GTD","GTE","R"],
 "ford":["Zetec","Titanium","ST-Line","Active","ST","Vignale"],
 "vauxhall":["Design","SE","SRi","Elite","Ultimate","GS"],
 "toyota":["Icon","Design","Excel","GR Sport","GR"],
 "nissan":["Visia","Acenta","N-Connecta","Tekna","N-Design"],
 "kia":["1","2","3","4","GT-Line","GT-Line S","GT"],
 "hyundai":["S","SE Connect","Premium","Ultimate","N Line","N"],
 "honda":["S","SE","SR","EX","Sport"],
 "peugeot":["Active","Allure","GT Line","GT"],
 "renault":["Play","Iconic","S Edition","RS Line"],
 "seat":["SE","SE Technology","FR","Xcellence","Cupra"],
 "skoda":["S","SE","SE L","Sportline","vRS"],
 "mini":["Classic","Sport","Exclusive","John Cooper Works"],
 "mazda":["SE-L","Sport","GT Sport","Homura"],
 "volvo":["Momentum","R-Design","Inscription","Plus","Ultimate"],
 "land rover":["S","SE","HSE","Autobiography","Dynamic"],
 "jaguar":["S","SE","HSE","R-Dynamic","R"],
 "tesla":["Standard Range","Long Range","Performance"],
 "mg":["Excite","Exclusive","Trophy"],
 "dacia":["Essential","Expression","Journey","Extreme"],
 "suzuki":["SZ3","SZ-T","SZ5","Ultra"],
 "fiat":["Pop","Lounge","Sport","La Prima"],
 "citroen":["Touch","Feel","Flair","Shine"],
 "polestar":["Standard","Plus","Performance"],
 "cupra":["V1","V2","V3","VZ"],
}
def trims(make): return TRIM.get(make, ["Base","Mid","Top"])

# ---- CARS: make -> [(model, gen, yr_from, yr_to, body, fuel)] ----
CARS={
 "audi":[("A1","GB",2018,2026,"hatchback",PH),("A3","8V",2015,2020,"hatchback",PDH),("A3","8Y",2020,2026,"hatchback",PHE),
   ("A4","B9",2015,2026,"saloon",PDH),("A5","F5",2016,2026,"coupe",PD),("A6","C8",2018,2026,"saloon",PDH),
   ("Q2","GA",2016,2026,"suv",PD),("Q3","F3",2018,2026,"suv",PDH),("Q5","FY",2016,2026,"suv",PDH),
   ("Q7","4M",2015,2026,"suv",PDH),("Q8 e-tron","GE",2019,2026,"suv",E),("TT","FV",2015,2023,"coupe",P)],
 "bmw":[("1 Series","F20",2015,2019,"hatchback",PD),("1 Series","F40",2019,2026,"hatchback",PDH),
   ("2 Series","F44",2020,2026,"saloon",PD),("3 Series","F30",2015,2019,"saloon",PDH),("3 Series","G20",2019,2026,"saloon",PHE),
   ("4 Series","G22",2020,2026,"coupe",PD),("5 Series","G30",2017,2023,"saloon",PDH),("5 Series","G60",2023,2026,"saloon",PHE),
   ("X1","F48",2015,2022,"suv",PD),("X1","U11",2022,2026,"suv",PHE),("X3","G01",2017,2026,"suv",PDH),
   ("X5","G05",2018,2026,"suv",PDH),("i4","G26",2021,2026,"saloon",E),("iX","I20",2021,2026,"suv",E)],
 "mercedes-benz":[("A-Class","W176",2015,2018,"hatchback",PD),("A-Class","W177",2018,2026,"hatchback",PDH),
   ("C-Class","W205",2015,2021,"saloon",PDH),("C-Class","W206",2021,2026,"saloon",PH),
   ("E-Class","W213",2016,2023,"saloon",PDH),("GLA","H247",2020,2026,"suv",PDH),("GLC","X253",2015,2022,"suv",PDH),
   ("GLC","X254",2022,2026,"suv",PH),("EQA","H243",2021,2026,"suv",E),("EQC","N293",2019,2024,"suv",E)],
 "volkswagen":[("Polo","AW",2017,2026,"hatchback",P),("Golf","Mk7",2015,2020,"hatchback",PDH),("Golf","Mk8",2020,2026,"hatchback",PDH),
   ("T-Roc","A1",2017,2026,"suv",PD),("T-Cross","C1",2019,2026,"suv",P),("Tiguan","AD",2016,2024,"suv",PDH),
   ("Passat","B8",2015,2023,"saloon",PDH),("ID.3","E1",2020,2026,"hatchback",E),("ID.4","E2",2021,2026,"suv",E),
   ("Up","AA",2015,2023,"hatchback",PE),("Arteon","3H",2017,2024,"saloon",PDH)],
 "ford":[("Fiesta","Mk7",2017,2023,"hatchback",PH),("Focus","Mk4",2018,2026,"hatchback",PDH),
   ("Puma","J1",2019,2026,"suv",PH),("Kuga","CX482",2019,2026,"suv",PDH),("Mustang Mach-E","CX727",2020,2026,"suv",E),
   ("EcoSport","B515",2015,2022,"suv",PD),("Mondeo","CD391",2015,2022,"saloon",PDH)],
 "vauxhall":[("Corsa","F",2019,2026,"hatchback",PE),("Astra","L",2021,2026,"hatchback",PHE),
   ("Mokka","B",2020,2026,"suv",PE),("Crossland","P",2017,2024,"suv",PD),("Grandland","A",2017,2026,"suv",PDH),
   ("Corsa","E",2015,2019,"hatchback",PD),("Astra","K",2015,2021,"hatchback",PD)],
 "toyota":[("Yaris","XP210",2020,2026,"hatchback",PH),("Corolla","E210",2018,2026,"hatchback",PH),
   ("C-HR","AX10",2016,2023,"suv",PH),("C-HR","AX20",2023,2026,"suv",PH),("RAV4","XA50",2018,2026,"suv",PH),
   ("Aygo X","AB40",2022,2026,"hatchback",P),("Prius","XW60",2023,2026,"hatchback",PH)],
 "nissan":[("Micra","K14",2017,2023,"hatchback",P),("Juke","F16",2019,2026,"suv",PH),
   ("Qashqai","J11",2015,2021,"suv",PD),("Qashqai","J12",2021,2026,"suv",PH),("Leaf","ZE1",2018,2026,"hatchback",E),
   ("X-Trail","T33",2022,2026,"suv",PH),("Ariya","FE0",2022,2026,"suv",E)],
 "kia":[("Picanto","JA",2017,2026,"hatchback",P),("Rio","YB",2017,2026,"hatchback",P),
   ("Ceed","CD",2018,2026,"hatchback",PDH),("Sportage","QL",2016,2021,"suv",PD),("Sportage","NQ5",2021,2026,"suv",PDH),
   ("Niro","SG2",2022,2026,"suv",PHE),("EV6","CV",2021,2026,"suv",E),("Sorento","MQ4",2020,2026,"suv",PDH)],
 "hyundai":[("i10","AC3",2019,2026,"hatchback",P),("i20","BC3",2020,2026,"hatchback",PH),
   ("i30","PD",2017,2026,"hatchback",PD),("Tucson","NX4",2021,2026,"suv",PDH),("Kona","SX2",2023,2026,"suv",PHE),
   ("Ioniq 5","NE",2021,2026,"suv",E),("Santa Fe","MX5",2024,2026,"suv",PH)],
 "honda":[("Jazz","GR",2020,2026,"hatchback",PH),("Civic","FK",2017,2022,"hatchback",PD),("Civic","FL",2022,2026,"hatchback",PH),
   ("CR-V","RW",2018,2023,"suv",PH),("CR-V","RS",2023,2026,"suv",PH),("HR-V","RV",2021,2026,"suv",PH),("e","ZC7",2020,2024,"hatchback",E)],
 "peugeot":[("208","P21",2019,2026,"hatchback",PE),("2008","P24",2019,2026,"suv",PE),
   ("308","P51",2021,2026,"hatchback",PHE),("3008","P84",2016,2024,"suv",PDH),("5008","P87",2017,2024,"suv",PD)],
 "renault":[("Clio","V",2019,2026,"hatchback",PH),("Captur","JB",2019,2026,"suv",PH),
   ("Megane","BFB",2016,2022,"hatchback",PD),("Austral","XN",2022,2026,"suv",PH),("Zoe","BG",2015,2024,"hatchback",E)],
 "seat":[("Ibiza","KJ",2017,2026,"hatchback",P),("Leon","KL",2020,2026,"hatchback",PDH),
   ("Arona","KJ7",2017,2026,"suv",P),("Ateca","5F",2016,2026,"suv",PD)],
 "skoda":[("Fabia","PJ",2021,2026,"hatchback",P),("Octavia","NX",2020,2026,"hatchback",PDH),
   ("Kamiq","NW",2019,2026,"suv",P),("Karoq","NU",2017,2026,"suv",PD),("Enyaq","5A",2021,2026,"suv",E),("Superb","3V",2015,2023,"saloon",PDH)],
 "mini":[("Hatch","F56",2015,2023,"hatchback",P),("Hatch","F66",2024,2026,"hatchback",PE),
   ("Countryman","F60",2017,2023,"suv",PH),("Countryman","U25",2024,2026,"suv",PE),("Electric","F56e",2020,2024,"hatchback",E)],
 "mazda":[("Mazda2","DJ",2015,2026,"hatchback",PH),("Mazda3","BP",2019,2026,"hatchback",P),
   ("CX-30","DM",2019,2026,"suv",P),("CX-5","KF",2017,2026,"suv",PD),("MX-5","ND",2015,2026,"convertible",P),("MX-30","DR",2020,2026,"suv",E)],
 "volvo":[("XC40","536",2017,2026,"suv",PHE),("XC60","246",2017,2026,"suv",PDH),("XC90","256",2015,2026,"suv",PDH),
   ("V60","225",2018,2026,"estate",PDH),("EX30","436",2024,2026,"suv",E)],
 "land rover":[("Range Rover Evoque","L551",2019,2026,"suv",PDH),("Range Rover Velar","L560",2017,2026,"suv",PDH),
   ("Range Rover Sport","L461",2022,2026,"suv",PDH),("Discovery Sport","L550",2015,2026,"suv",PDH),("Defender","L663",2020,2026,"suv",PDH)],
 "jaguar":[("XE","X760",2015,2024,"saloon",PD),("XF","X260",2015,2026,"saloon",PD),("F-Pace","X761",2016,2026,"suv",PDH),
   ("E-Pace","X540",2017,2026,"suv",PDH),("I-Pace","X590",2018,2026,"suv",E)],
 "tesla":[("Model 3","",2019,2026,"saloon",E),("Model Y","",2021,2026,"suv",E),("Model S","",2015,2026,"saloon",E),("Model X","",2016,2026,"suv",E)],
 "mg":[("MG3","",2018,2026,"hatchback",PH),("MG4","",2022,2026,"hatchback",E),("HS","",2019,2026,"suv",PH),("ZS","",2017,2026,"suv",PE),("MG5","",2020,2026,"estate",E)],
 "dacia":[("Sandero","B8",2021,2026,"hatchback",P),("Duster","HM",2018,2026,"suv",P),("Jogger","",2022,2026,"estate",PH),("Spring","",2024,2026,"hatchback",E)],
 "suzuki":[("Swift","AZ",2017,2026,"hatchback",PH),("Vitara","LY",2015,2026,"suv",PH),("S-Cross","JY",2015,2026,"suv",PH),("Ignis","MF",2017,2026,"suv",PH)],
 "fiat":[("500","312",2015,2024,"hatchback",PH),("500e","332",2020,2026,"hatchback",E),("Panda","319",2015,2026,"hatchback",PH),("Tipo","356",2016,2026,"hatchback",PD)],
 "citroen":[("C3","B618",2016,2026,"hatchback",PD),("C4","C41",2020,2026,"hatchback",PE),("C5 Aircross","C84",2018,2026,"suv",PDH),("Ami","",2022,2026,"hatchback",E)],
 "polestar":[("2","",2020,2026,"saloon",E),("3","",2024,2026,"suv",E),("4","",2024,2026,"suv",E)],
 "cupra":[("Formentor","KM",2020,2026,"suv",PH),("Born","K1",2021,2026,"hatchback",E),("Leon","KL",2020,2026,"hatchback",PH)],
 "porsche":[("911","992",2019,2026,"coupe",P),("Cayenne","9YA",2017,2026,"suv",PH),("Macan","95B",2015,2026,"suv",P),("Taycan","J1",2019,2026,"saloon",E)],
}

# ---- VANS ----
VANS={
 "ford":[("Transit","V363",2015,2026,"panel van",DE),("Transit Custom","V362",2015,2026,"panel van",DE),
   ("Transit Connect","PJ2",2015,2026,"panel van",D),("Ranger","P703",2015,2026,"pickup",PD)],
 "volkswagen":[("Transporter","T6",2015,2026,"panel van",["diesel","electric"]),("Caddy","SB",2020,2026,"panel van",PD),("Crafter","SY",2017,2026,"panel van",D)],
 "mercedes-benz":[("Sprinter","W907",2018,2026,"panel van",["diesel","electric"]),("Vito","W447",2015,2026,"panel van",["diesel","electric"]),("Citan","W420",2021,2026,"panel van",D)],
 "vauxhall":[("Vivaro","K0",2019,2026,"panel van",["diesel","electric"]),("Combo","K9",2018,2026,"panel van",["diesel","electric"]),("Movano","",2021,2026,"panel van",["diesel","electric"])],
 "peugeot":[("Partner","K9",2018,2026,"panel van",["diesel","electric"]),("Expert","K0",2016,2026,"panel van",["diesel","electric"]),("Boxer","",2015,2026,"panel van",["diesel","electric"])],
 "citroen":[("Berlingo","K9",2018,2026,"panel van",["diesel","electric"]),("Dispatch","K0",2016,2026,"panel van",["diesel","electric"]),("Relay","",2015,2026,"panel van",["diesel","electric"])],
 "renault":[("Trafic","X82",2015,2026,"panel van",["diesel","electric"]),("Master","X62",2015,2026,"panel van",["diesel","electric"]),("Kangoo","",2015,2026,"panel van",["diesel","electric"])],
 "toyota":[("Proace","",2016,2026,"panel van",["diesel","electric"]),("Hilux","AN120",2016,2026,"pickup",D)],
 "nissan":[("Primastar","",2021,2026,"panel van",["diesel","electric"]),("Townstar","",2022,2026,"panel van",["petrol","electric"]),("Navara","D23",2015,2024,"pickup",D)],
 "fiat":[("Ducato","",2015,2026,"panel van",["diesel","electric"]),("Doblo","",2015,2026,"panel van",["diesel","electric"]),("Scudo","",2022,2026,"panel van",["diesel","electric"])],
 "iveco":[("Daily","",2015,2026,"panel van",["diesel","electric"])],
 "maxus":[("Deliver 9","",2020,2026,"panel van",["diesel","electric"]),("eDeliver 3","",2021,2026,"panel van",E),("T90 EV","",2023,2026,"pickup",E)],
}

# ---- MOTORBIKES (no trims / no fuel variety: petrol or electric) ----
BIKES={
 "honda":[("CB500F","",2015,2026,"naked",P),("CB650R","",2019,2026,"naked",P),("CBR650R","",2019,2026,"sport",P),
   ("Africa Twin","",2016,2026,"adventure",P),("CRF300L","",2021,2026,"trail",P),("PCX125","",2015,2026,"scooter",P),("Gold Wing","",2018,2026,"tourer",P)],
 "yamaha":[("MT-07","",2015,2026,"naked",P),("MT-09","",2015,2026,"naked",P),("YZF-R1","",2015,2026,"sport",P),
   ("YZF-R7","",2022,2026,"sport",P),("Tenere 700","",2019,2026,"adventure",P),("NMAX 125","",2015,2026,"scooter",P),("Tracer 9","",2021,2026,"tourer",P)],
 "kawasaki":[("Z650","",2017,2026,"naked",P),("Z900","",2017,2026,"naked",P),("Ninja 650","",2017,2026,"sport",P),
   ("Ninja ZX-10R","",2015,2026,"sport",P),("Versys 650","",2015,2026,"adventure",P),("Z H2","",2020,2026,"naked",P)],
 "suzuki":[("GSX-R750","",2015,2026,"sport",P),("SV650","",2016,2026,"naked",P),("V-Strom 650","",2015,2026,"adventure",P),
   ("GSX-S1000","",2015,2026,"naked",P),("Hayabusa","",2021,2026,"sport",P)],
 "bmw":[("R 1250 GS","",2019,2026,"adventure",P),("S 1000 RR","",2015,2026,"sport",P),("F 900 R","",2020,2026,"naked",P),
   ("R nineT","",2015,2026,"naked",P),("CE 04","",2022,2026,"scooter",E)],
 "triumph":[("Street Triple","",2015,2026,"naked",P),("Speed Triple","",2015,2026,"naked",P),("Tiger 900","",2020,2026,"adventure",P),
   ("Trident 660","",2021,2026,"naked",P),("Bonneville T120","",2016,2026,"classic",P),("Rocket 3","",2019,2026,"cruiser",P)],
 "ducati":[("Monster","",2015,2026,"naked",P),("Panigale V4","",2018,2026,"sport",P),("Multistrada V4","",2021,2026,"adventure",P),
   ("Scrambler","",2015,2026,"classic",P),("Diavel","",2015,2026,"cruiser",P)],
 "ktm":[("390 Duke","",2015,2026,"naked",P),("790 Duke","",2018,2026,"naked",P),("1290 Super Duke R","",2015,2026,"naked",P),
   ("890 Adventure","",2021,2026,"adventure",P),("1290 Super Adventure","",2015,2026,"adventure",P)],
 "harley-davidson":[("Iron 883","",2015,2023,"cruiser",P),("Street Bob","",2018,2026,"cruiser",P),("Fat Boy","",2015,2026,"cruiser",P),
   ("Pan America","",2021,2026,"adventure",P),("Nightster","",2022,2026,"cruiser",P)],
 "royal enfield":[("Classic 350","",2021,2026,"classic",P),("Meteor 350","",2020,2026,"cruiser",P),("Himalayan","",2016,2026,"adventure",P),("Continental GT 650","",2018,2026,"classic",P)],
 "aprilia":[("RS 660","",2020,2026,"sport",P),("Tuono 660","",2021,2026,"naked",P),("RSV4","",2015,2026,"sport",P),("Tuareg 660","",2022,2026,"adventure",P)],
}

def clamp(a,b): return max(2015,a), min(2026,b)

def rows(group, klass):
    out=[]
    for make, models in group.items():
        for (model, gen, yf, yt, body, fuel) in models:
            yf,yt=clamp(yf,yt)
            out.append({"class":klass,"make":make,"model":model,"generation":gen,
                        "year_from":yf,"year_to":yt,"body_style":body,
                        "fuel":fuel,"trims":([] if klass=="motorbike" else trims(make)),
                        "colours":COLOURS,"has_3d":False,"manifest_url":None})
    return out

index=rows(CARS,"car")+rows(VANS,"van")+rows(BIKES,"motorbike")

# join has_3d from the live 3D catalogue
try:
    cat=json.loads(urllib.request.urlopen(f"{PUB}/catalogue.json",timeout=40).read())
    have={(c["make"].lower(),c["model"].lower()):c for c in cat}
    for e in index:
        key=(e["make"].lower(),e["model"].lower())
        if key in have:
            e["has_3d"]=True; e["manifest_url"]=have[key]["manifest_url"]
except Exception as ex:
    print("catalogue join skipped:",ex)

payload={"generated":"2015-2026 UK master index (representative)","colours":COLOURS,
         "counts":{}, "vehicles":index}
from collections import Counter
c=Counter(e["class"] for e in index)
mk=len(set((e["class"],e["make"]) for e in index))
payload["counts"]={"total":len(index),"cars":c["car"],"vans":c["van"],
                   "motorbikes":c["motorbike"],"makes":mk,"with_3d":sum(e["has_3d"] for e in index)}

# upload
def up(path,data,ct):
    rq=urllib.request.Request(f"{BASE}/car-renders/{path}",data=data,method="POST")
    rq.add_header("apikey",SBKEY);rq.add_header("Authorization","Bearer "+SBKEY);rq.add_header("Content-Type",ct);rq.add_header("x-upsert","true")
    urllib.request.urlopen(rq,timeout=120).read()
up("vehicle_index.json", json.dumps(payload).encode(), "application/json")
open("vehicle_index.json","w").write(json.dumps(payload,indent=1))
print("COUNTS:",json.dumps(payload["counts"]))
print("PUBLISHED", f"{PUB}/vehicle_index.json")

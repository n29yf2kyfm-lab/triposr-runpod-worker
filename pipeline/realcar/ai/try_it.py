"""try_it.py: test the vehicle model yourself, on photos it never saw, with checks a fake could not pass.

Paste it all into a Google Colab cell (colab.research.google.com, works from a phone's browser) and run it,
or on any computer:  python3 try_it.py   It needs nothing but Python 3.9+ and an internet connection, and
takes 3-5 minutes (most of it the 350 MB image encoder downloading).

What it does, in the open:
1. Downloads the model's code and trained weights from GitHub at one fixed commit, and refuses them if
   their SHA-256 fingerprints are not the ones printed here (so you know what you ran); then the image
   encoder (CLIP, OpenAI's, from Hugging Face), checked the same way by the code.
2. Reads 29 Wikimedia Commons photos the model never trained on, and scores its answers against
   answers written by hand from looking at each photo (kind, the way it points, the paint).
3. Catch-a-faker checks, on the same photos changed on the spot: mirrored (the side must flip), red
   and blue swapped (the paint must swap with them), turned grey (the paint must read grey, white,
   silver or black), and the same photo twice (the same numbers). Answers learned from labels, or
   written in, could not follow pictures changed here.
4. Put a photo address of your own in MY_PHOTO to see what it says about it.
"""
MY_PHOTO = ""        # e.g. "https://upload.wikimedia.org/...jpg": a photo of a vehicle, from the side or three-quarter

import hashlib, importlib, io, os, subprocess, sys, time, urllib.request

for mod, pkg in (("numpy", "numpy"), ("PIL", "pillow"), ("onnxruntime", "onnxruntime")):
    try:
        importlib.import_module(mod)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
import numpy as np
from PIL import Image

COMMIT = "d1f69956b662fb530168f522aedab1417ac680a1"
REPO = f"https://raw.githubusercontent.com/n29yf2kyfm-lab/triposr-runpod-worker/{COMMIT}/pipeline/realcar/ai/"
FILES = {"vision.py": "ab382aaf3b1096c69d8e2591e5320c47d1ef4309ef89441453064fc6d65f4947",
         "heads.py": "c9cdd81b71f876788f05e899de531e1c72a15cc51683c170693eacedaee56f94",
         "heads.json": "3f4016542e47c3e12ea31b3c0fab59df193238499b643d9af74aa7d6284ec44c"}
UA = {"User-Agent": "vehicle-ai-try-it/1.0 (https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"}
HERE = os.path.abspath("vehicle_ai_try")
os.makedirs(HERE, exist_ok=True)


def get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


print("1. The model's files, from GitHub at commit", COMMIT[:8])
for name, want in FILES.items():
    data = get(REPO + name)
    got = hashlib.sha256(data).hexdigest()
    print(f"   {name:10s} sha256 {got[:16]}...", "OK" if got == want else "NOT THE PUBLISHED FILE")
    if got != want:
        raise SystemExit("stopped: a file is not the one this test pins")
    open(os.path.join(HERE, name), "wb").write(data)
sys.path.insert(0, HERE)
os.environ.setdefault("VEHICLE_AI_HOME", os.path.join(HERE, "cache"))
import vision, heads as H
hs, card = H.load_heads(os.path.join(HERE, "heads.json"))
enc = vision.Encoder()             # downloads the encoder once (350 MB) and checks its SHA-256
print("   image encoder", os.path.basename(enc.path), "checked; trained", card["trained"])


def read(im):
    e, ef = enc.embed([im])[0], enc.embed([im], flip=True)[0]
    return H.read(hs, card["paint"], (e, ef, H.colour_hist(im))), e


def photo(url):
    p = os.path.join(HERE, "photo.jpg")
    open(p, "wb").write(get(url))
    return vision.load(p)


# name, kind, the way it points, paint (each as a person looking at the photo answered; "a|b": either is right)
COMMONS = "https://thumb.wikimedia.org/wikipedia/commons/thumb/"
TEST = [
    ('audi s5', 'car', 'left', 'dark-blue', 'e/ee/2018_Audi_S5_sedan_front_4.11.18.jpg/1280px-2018_Audi_S5_sedan_front_4.11.18.jpg'),
    ('renault trafic', 'car|van', 'right', 'grey|taupe', '8/81/Renault_Trafic_Grand_Passenger_Black_Edition_dCi_115_%28II%2C_Facelift%29_%E2%80%93_Frontansicht%2C_1._September_2013%2C_M%C3%BCnster.jpg/1280px-Renault_Trafic_Grand_Passenger_Black_Edition_dCi_115_%28II%2C_Facelift%29_%E2%80%93_Frontansicht%2C_1._September_2013%2C_M%C3%BCnster.jpg'),
    ('ford fiesta', 'car', 'right', 'silver', 'a/ab/2010_Ford_Fiesta_%28WT%29_LX_5-door_hatchback_%282015-07-16%29_01.jpg/1280px-2010_Ford_Fiesta_%28WT%29_LX_5-door_hatchback_%282015-07-16%29_01.jpg'),
    ('volkswagen california', 'car|van', 'right', 'silver', '8/8b/2004-2010_Volkswagen_Multivan_TDI_van_01.jpg/1280px-2004-2010_Volkswagen_Multivan_TDI_van_01.jpg'),
    ('audi sq5', 'car', 'left', 'black', '1/1d/Audi_SQ5_TDI_%28Facelift%29_%E2%80%93_Frontansicht%2C_27._April_2014%2C_D%C3%BCsseldorf.jpg/1280px-Audi_SQ5_TDI_%28Facelift%29_%E2%80%93_Frontansicht%2C_27._April_2014%2C_D%C3%BCsseldorf.jpg'),
    ('mercedes c class', 'car', 'left', 'silver', '2/24/Mercedes-Benz_W206_IMG_5796.jpg/1280px-Mercedes-Benz_W206_IMG_5796.jpg'),
    ('mitsubishi l200', 'van', 'right', 'blue', 'd/de/1984_Mitsubishi_L200_Express_%28MC%29_2.3_Diesel_4WD_utility_%2822551245861%29_%28cropped%29.jpg/1280px-1984_Mitsubishi_L200_Express_%28MC%29_2.3_Diesel_4WD_utility_%2822551245861%29_%28cropped%29.jpg'),
    ('volkswagen id5', 'car', 'left', 'silver|white', '5/55/2025_Volkswagen_ID4_Pro_Redspot_front.jpg/1280px-2025_Volkswagen_ID4_Pro_Redspot_front.jpg'),
    ('suzuki alto', 'car', 'left', 'beige|champagne|pearl-white', '6/6a/2018-2020_Suzuki_Alto_X.jpg/1280px-2018-2020_Suzuki_Alto_X.jpg'),
    ('bmw m5', 'car', 'left', 'dark-green|green|turquoise', '8/80/BMW_M5_%28G90%29_MYLE_Festival_2025_DSC_9648.jpg/1280px-BMW_M5_%28G90%29_MYLE_Festival_2025_DSC_9648.jpg'),
    ('volvo xc70', 'car', 'right', 'silver', 'f/f8/VOLVO_XC70_V446K_China.jpg/1280px-VOLVO_XC70_V446K_China.jpg'),
    ('volkswagen multivan', 'car|van', 'left', 'white', '3/37/VW_Multivan_2.0_TDI_Life_%28VII%29_%E2%80%93_f_22012023.jpg/1280px-VW_Multivan_2.0_TDI_Life_%28VII%29_%E2%80%93_f_22012023.jpg'),
    ('man tge', 'van', 'left', 'white', '7/74/MAN_TGE_3.180_Kastenwagen.jpg/1280px-MAN_TGE_3.180_Kastenwagen.jpg'),
    ('mercedes s class', 'car', 'left', 'beige|champagne', '2/28/Mercedes-Benz_S430_W220.jpg/1280px-Mercedes-Benz_S430_W220.jpg'),
    ('mercedes slc class', 'car', 'left', 'red', '4/48/1988_Mercedes_SL_280.jpg/1280px-1988_Mercedes_SL_280.jpg'),
    ('toyota iq', 'car', 'right', 'white', 'b/b4/Proton_emas_geneva_2.jpg/1280px-Proton_emas_geneva_2.jpg'),
    ('rover 75', 'car', 'left', 'pearl-white|white', '1/13/Rover_75.jpg/1280px-Rover_75.jpg'),
    ('porsche boxster', 'car', 'left', 'silver', '7/7a/Porsche_718_Boxster_GTS_4.0_1X7A0320.jpg/1280px-Porsche_718_Boxster_GTS_4.0_1X7A0320.jpg'),
    ('renault master', 'van', 'right', 'dark-grey|grey|grey-blue', '2/20/2025_Renault_Master_in_Urban_Grey%2C_front_right%2C_06-12-2025.jpg/1280px-2025_Renault_Master_in_Urban_Grey%2C_front_right%2C_06-12-2025.jpg'),
    ('audi q6', 'car', 'right', 'white', '8/86/2022_SAIC-Audi_Q6.jpg/1280px-2022_SAIC-Audi_Q6.jpg'),
    ('ford sierra', 'car', 'left', '', '3/33/Ford_Sierra_CLX_1988_zweit%C3%BCrig.jpg/1280px-Ford_Sierra_CLX_1988_zweit%C3%BCrig.jpg'),
    ('mini roadster', 'car', 'left', 'white', 'b/b7/2012_Mini_John_Cooper_Works_Coupe_--_11-26-2011_front.jpg/1280px-2012_Mini_John_Cooper_Works_Coupe_--_11-26-2011_front.jpg'),
    ('bmw z4', 'car', 'right', 'red', '5/5d/2004_BMW_Z4_2.5_front.jpg/1280px-2004_BMW_Z4_2.5_front.jpg'),
    ('citroen relay', 'van', 'left', 'white', 'e/ed/2005_Citroen_Relay_HDi_1100_Enterprise_2.0_Front.jpg/1280px-2005_Citroen_Relay_HDi_1100_Enterprise_2.0_Front.jpg'),
    ('peugeot 205', 'car', 'left', 'red', '5/55/Peugeot_205_front_20080121.jpg/1280px-Peugeot_205_front_20080121.jpg'),
    ('fiat fiorino', 'van', 'left', 'white', '8/81/Fiat_Fiorino_1.4_ELX_2014_%2820890089331%29_%28cropped%29.jpg/1280px-Fiat_Fiorino_1.4_ELX_2014_%2820890089331%29_%28cropped%29.jpg'),
    ('austin morris mini', 'car', 'left', 'silver', 'b/be/2003_Mini_Cooper_Automatic_1.6_Front.jpg/1280px-2003_Mini_Cooper_Automatic_1.6_Front.jpg'),
    ('peugeot partner', 'van', 'left', 'white', '0/05/Peugeot_Partner_2_%282008-2012%29.JPG/1280px-Peugeot_Partner_2_%282008-2012%29.JPG'),
    ('porsche taycan', 'car', 'right', 'silver|white', 'd/dc/2020_Porsche_Taycan_4S_79kWh_Front.jpg/1280px-2020_Porsche_Taycan_4S_79kWh_Front.jpg'),
]

print(f"\n2. {len(TEST)} photos it never trained on, against answers written by looking at each")
right = {"kind": 0, "side": 0, "colour": 0}
asked = {"kind": 0, "side": 0, "colour": 0}
pics = []
for name, kind, side, colour, path in TEST:
    try:
        im = photo(COMMONS + path)
    except Exception as e:
        print(f"   {name:18s} could not download ({e})")
        continue
    a, e = read(im)
    pics.append((name, im, a, e))
    marks = []
    for what, truth in (("kind", kind), ("side", side), ("colour", colour)):
        if not truth:
            continue
        ok = a[what]["answer"] in truth.split("|")
        asked[what] += 1
        right[what] += ok
        marks.append(f"{what} {a[what]['answer']}{'' if ok else ' (WRONG: ' + truth + ')'}")
    print(f"   {name:18s} " + ", ".join(marks))
    time.sleep(1)                  # Wikimedia asks for gentle downloads
chance = {"kind": "1 in 3", "side": "1 in 2", "colour": f"1 in {len(hs['colour'].classes)}"}
for what in right:
    if asked[what]:
        print(f"   {what:6s}: {right[what]} of {asked[what]} right ({100 * right[what] / asked[what]:.0f}%); guessing would get {chance[what]}")


def paint(answer):
    return np.array([int(card["paint"][answer][i:i + 2], 16) for i in (1, 3, 5)])


print("\n3. Catch-a-faker checks, on the same photos changed here")
mirror = [read(im.transpose(Image.FLIP_LEFT_RIGHT))[0]["side"]["answer"] != a["side"]["answer"] for _, im, a, _ in pics]
print(f"   mirrored, the side flips: {sum(mirror)} of {len(mirror)}  (the side reading is built to flip with a mirror:"
      " this shows the code reads the picture, not a list of answers)")
swapped, sw_n = 0, 0
for name, im, a, _ in pics:
    c = paint(a["colour"]["answer"])
    if abs(int(c[0]) - int(c[2])) < 60:
        continue                   # grey, white, black...: swapping red and blue changes nothing
    r, g, b = im.split()
    s = read(Image.merge("RGB", (b, g, r)))[0]["colour"]["answer"]
    sw_n += 1
    swapped += (paint(s)[0] > paint(s)[2]) != (c[0] > c[2])
    print(f"   {name:18s} {a['colour']['answer']:11s} -> red and blue swapped -> {s}")
print(f"   red and blue swapped, the paint swaps: {swapped} of {sw_n}")
NEUTRAL = {"white", "pearl-white", "silver", "grey", "dark-grey", "black"}
grey_ok = sum(read(im.convert("L").convert("RGB"))[0]["colour"]["answer"] in NEUTRAL for _, im, _, _ in pics)
print(f"   turned grey, the paint reads a grey, white, silver or black: {grey_ok} of {len(pics)}")
same = all(np.array_equal(read(im)[1], e) for _, im, _, e in pics[:3])
print("   the same photo twice gives the same numbers:", "yes" if same else "NO")
noise = Image.fromarray(np.random.default_rng(0).integers(0, 256, (300, 450, 3), dtype=np.uint8))
n = read(noise)[0]
print(f"   random noise (no vehicle at all): it still answers {n['kind']['answer']} {n['kind']['p']:.0%},"
      f" {n['colour']['answer']}: it cannot tell a vehicle from none (a known limit, in its README)")

if MY_PHOTO:
    a, _ = read(photo(MY_PHOTO))
    print("\n4. Your photo:", {k: (v["answer"], round(v["p"], 2)) for k, v in a.items()})

print("\nIts README says, on photos it did not train on: kind 93%, side 95%, colour 70% (90% to the next shade).")

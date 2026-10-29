"""try_it.py: test the vehicle model yourself, on photos it never saw, against controls.

Paste it all into a Google Colab cell (colab.research.google.com, works from a phone's browser) and run it,
or on any computer:  python3 try_it.py   It needs Python 3.9+ and the internet; about 5 minutes, most of it
the two image encoders downloading (720 MB). Three AI models (Claude Haiku, Sonnet and Fable) ran and
audited it before you; what they found wrong was fixed.

What it does, in the open:
1. Downloads the model's code and trained weights from GitHub at one fixed commit, and stops if any
   file's SHA-256 is not the one printed here; then the image encoders (Google's SigLIP and Meta's DINOv2,
   from Hugging Face), checked the same way by the code.
2. Checks that the 29 test photos (Wikimedia Commons) were not trained on: each is compared by its looks
   with every picture the model was trained on (their fingerprints are published with it).
3. Scores the model's answers against answers written by a person looking at each photo: strictly (the
   one answer a person gives) and leniently (also a fair second, e.g. a Multivan is a van, but is
   registered as a car), against random guessing and always giving the commonest answer.
4. Controls: the same photos with the trained weights swapped for random ones (should fall to guessing:
   the skill is in the training, not the code); the photos recoloured on the spot (red and blue swapped:
   the paint read should move with it; turned grey: a colour should read grey, white, silver or black).
5. Blind test (BLIND photos): pictures chosen at random when you run it, that nobody picked; you type
   what you see before the model's answer shows. Needs you at the keyboard (Colab or a terminal).
6. MY_PHOTO: a photo address of your own.
"""
MY_PHOTO = ""        # e.g. "https://upload.wikimedia.org/...jpg": a vehicle from the side or three-quarter
BLIND = 5            # 0 to skip the blind test

import collections, hashlib, importlib, json, os, random, subprocess, sys, time, urllib.parse, urllib.request

for mod, pkg in (("numpy", "numpy"), ("PIL", "pillow"), ("onnxruntime", "onnxruntime")):
    try:
        importlib.import_module(mod)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
import numpy as np
from PIL import Image

COMMIT = "786b305b4ab2d2927c101389636219c7b8b5f2e8"
REPO = f"https://raw.githubusercontent.com/n29yf2kyfm-lab/triposr-runpod-worker/{COMMIT}/pipeline/realcar/ai/"
FILES = {"vision.py": "5029ec0b2214a6abd7a5d0c2026fff040cf4aa090e0809a8d74404ac39d88416",
         "heads.py": "5ebed26f65fbf2bdbe6f9aade5e51464d542aeafb35ee1f36d87a283731ecefc",
         "heads.json": "a27c839c5be3cc3963822703dfc152586d1858cbe04f19b0ecce389f51267d37",
         "train_pictures.json": "8995a3b9d25602ae55b587e511d5acf4f35b38ccd29f3cb520dca75e560b6d57"}
UA = {"User-Agent": "vehicle-ai-try-it/2.0 (https://github.com/n29yf2kyfm-lab/triposr-runpod-worker)"}
HERE = os.path.abspath("vehicle_ai_try")
os.makedirs(HERE, exist_ok=True)


def get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))


print("1. The model's files, from GitHub at commit", COMMIT[:8])
for name, want in FILES.items():
    data = get(REPO + name)
    got = hashlib.sha256(data).hexdigest()
    print(f"   {name:18s} sha256 {got[:16]}...", "OK" if got == want else "NOT THE PUBLISHED FILE")
    if got != want:
        raise SystemExit("stopped: a file is not the one this test pins")
    open(os.path.join(HERE, name), "wb").write(data)
sys.path.insert(0, HERE)
os.environ.setdefault("VEHICLE_AI_HOME", os.path.join(HERE, "cache"))
import vision, heads as H
hs, card = H.load_heads(os.path.join(HERE, "heads.json"))
seen = json.load(open(os.path.join(HERE, "train_pictures.json")))["dhash"]
enc = vision.encoders(",".join(e["name"] for e in card["encoders"]))      # downloaded once, each checked by its SHA-256
print(f"   image encoders {enc.path.replace(os.path.dirname(enc.path.split(',')[0]) + '/', '')} checked;"
      f" heads trained {card['trained']} on {len(seen)} pictures")


def features(im):
    return enc.embed([im])[0], enc.embed([im], flip=True)[0], H.colour_hist(im)


def photo(url):
    p = os.path.join(HERE, "photo.jpg")
    open(p, "wb").write(get(url))
    return vision.load(p)


# name, kind, the way it points, paint: as a person looking at the photo answered. "a|b": a is the
# person's answer, b is also fair (scored only leniently); "" not asked (a photo too unclear to say)
COMMONS = "https://thumb.wikimedia.org/wikipedia/commons/thumb/"
TEST = [
    ('audi s5', 'car', 'left', 'dark-blue', 'e/ee/2018_Audi_S5_sedan_front_4.11.18.jpg/1280px-2018_Audi_S5_sedan_front_4.11.18.jpg'),
    ('renault trafic', 'van|car', 'right', 'grey|taupe', '8/81/Renault_Trafic_Grand_Passenger_Black_Edition_dCi_115_%28II%2C_Facelift%29_%E2%80%93_Frontansicht%2C_1._September_2013%2C_M%C3%BCnster.jpg/1280px-Renault_Trafic_Grand_Passenger_Black_Edition_dCi_115_%28II%2C_Facelift%29_%E2%80%93_Frontansicht%2C_1._September_2013%2C_M%C3%BCnster.jpg'),
    ('ford fiesta', 'car', 'right', 'silver', 'a/ab/2010_Ford_Fiesta_%28WT%29_LX_5-door_hatchback_%282015-07-16%29_01.jpg/1280px-2010_Ford_Fiesta_%28WT%29_LX_5-door_hatchback_%282015-07-16%29_01.jpg'),
    ('volkswagen multivan t5', 'van|car', 'right', 'silver', '8/8b/2004-2010_Volkswagen_Multivan_TDI_van_01.jpg/1280px-2004-2010_Volkswagen_Multivan_TDI_van_01.jpg'),
    ('audi sq5', 'car', 'left', 'black', '1/1d/Audi_SQ5_TDI_%28Facelift%29_%E2%80%93_Frontansicht%2C_27._April_2014%2C_D%C3%BCsseldorf.jpg/1280px-Audi_SQ5_TDI_%28Facelift%29_%E2%80%93_Frontansicht%2C_27._April_2014%2C_D%C3%BCsseldorf.jpg'),
    ('mercedes c class', 'car', 'left', 'silver', '2/24/Mercedes-Benz_W206_IMG_5796.jpg/1280px-Mercedes-Benz_W206_IMG_5796.jpg'),
    ('mitsubishi l200', 'van', 'right', 'blue', 'd/de/1984_Mitsubishi_L200_Express_%28MC%29_2.3_Diesel_4WD_utility_%2822551245861%29_%28cropped%29.jpg/1280px-1984_Mitsubishi_L200_Express_%28MC%29_2.3_Diesel_4WD_utility_%2822551245861%29_%28cropped%29.jpg'),
    ('volkswagen id4', 'car', 'left', 'silver|white', '5/55/2025_Volkswagen_ID4_Pro_Redspot_front.jpg/1280px-2025_Volkswagen_ID4_Pro_Redspot_front.jpg'),
    ('suzuki alto', 'car', 'left', 'beige|champagne|pearl-white', '6/6a/2018-2020_Suzuki_Alto_X.jpg/1280px-2018-2020_Suzuki_Alto_X.jpg'),
    ('bmw m5', 'car', 'left', 'green|turquoise|dark-green', '8/80/BMW_M5_%28G90%29_MYLE_Festival_2025_DSC_9648.jpg/1280px-BMW_M5_%28G90%29_MYLE_Festival_2025_DSC_9648.jpg'),
    ('volvo ev (china)', 'car', 'right', 'silver', 'f/f8/VOLVO_XC70_V446K_China.jpg/1280px-VOLVO_XC70_V446K_China.jpg'),
    ('volkswagen multivan', 'van|car', 'left', 'white', '3/37/VW_Multivan_2.0_TDI_Life_%28VII%29_%E2%80%93_f_22012023.jpg/1280px-VW_Multivan_2.0_TDI_Life_%28VII%29_%E2%80%93_f_22012023.jpg'),
    ('man tge', 'van', 'left', 'white', '7/74/MAN_TGE_3.180_Kastenwagen.jpg/1280px-MAN_TGE_3.180_Kastenwagen.jpg'),
    ('mercedes s class', 'car', 'left', 'champagne|beige', '2/28/Mercedes-Benz_S430_W220.jpg/1280px-Mercedes-Benz_S430_W220.jpg'),
    ('mercedes sl r107', 'car', 'left', 'red', '4/48/1988_Mercedes_SL_280.jpg/1280px-1988_Mercedes_SL_280.jpg'),
    ('proton emas', 'car', 'right', 'white', 'b/b4/Proton_emas_geneva_2.jpg/1280px-Proton_emas_geneva_2.jpg'),
    ('rover 75', 'car', 'left', 'pearl-white|white', '1/13/Rover_75.jpg/1280px-Rover_75.jpg'),
    ('porsche boxster', 'car', 'left', 'silver', '7/7a/Porsche_718_Boxster_GTS_4.0_1X7A0320.jpg/1280px-Porsche_718_Boxster_GTS_4.0_1X7A0320.jpg'),
    ('renault master', 'van', 'right', 'grey|dark-grey|grey-blue', '2/20/2025_Renault_Master_in_Urban_Grey%2C_front_right%2C_06-12-2025.jpg/1280px-2025_Renault_Master_in_Urban_Grey%2C_front_right%2C_06-12-2025.jpg'),
    ('audi q6', 'car', 'right', 'white', '8/86/2022_SAIC-Audi_Q6.jpg/1280px-2022_SAIC-Audi_Q6.jpg'),
    ('ford sierra', 'car', 'left', 'champagne|beige|taupe', '3/33/Ford_Sierra_CLX_1988_zweit%C3%BCrig.jpg/1280px-Ford_Sierra_CLX_1988_zweit%C3%BCrig.jpg'),
    ('mini coupe', 'car', 'left', 'white', 'b/b7/2012_Mini_John_Cooper_Works_Coupe_--_11-26-2011_front.jpg/1280px-2012_Mini_John_Cooper_Works_Coupe_--_11-26-2011_front.jpg'),
    ('bmw z4', 'car', 'right', 'red', '5/5d/2004_BMW_Z4_2.5_front.jpg/1280px-2004_BMW_Z4_2.5_front.jpg'),
    ('citroen relay', 'van', 'left', 'white', 'e/ed/2005_Citroen_Relay_HDi_1100_Enterprise_2.0_Front.jpg/1280px-2005_Citroen_Relay_HDi_1100_Enterprise_2.0_Front.jpg'),
    ('peugeot 205', 'car', 'left', 'red', '5/55/Peugeot_205_front_20080121.jpg/1280px-Peugeot_205_front_20080121.jpg'),
    ('fiat fiorino', 'van', 'left', 'white', '8/81/Fiat_Fiorino_1.4_ELX_2014_%2820890089331%29_%28cropped%29.jpg/1280px-Fiat_Fiorino_1.4_ELX_2014_%2820890089331%29_%28cropped%29.jpg'),
    ('austin morris mini', 'car', 'left', 'silver', 'b/be/2003_Mini_Cooper_Automatic_1.6_Front.jpg/1280px-2003_Mini_Cooper_Automatic_1.6_Front.jpg'),
    ('peugeot partner', 'van', 'left', 'white', '0/05/Peugeot_Partner_2_%282008-2012%29.JPG/1280px-Peugeot_Partner_2_%282008-2012%29.JPG'),
    ('porsche taycan', 'car', 'right', 'white|silver', 'd/dc/2020_Porsche_Taycan_4S_79kWh_Front.jpg/1280px-2020_Porsche_Taycan_4S_79kWh_Front.jpg'),
]

print(f"\n2. Were the {len(TEST)} test photos trained on? Each against all {len(seen)} training pictures, by looks")
pics = []
for name, kind, side, colour, path in TEST:
    try:
        im = photo(COMMONS + path)
    except Exception as e:
        print(f"   {name:22s} could not download ({e})")
        continue
    near = min(vision.dhash_bits(vision.dhash(im), s) for s in seen)
    pics.append((name, {"kind": kind, "side": side, "colour": colour}, im, features(im), near))
    time.sleep(1)                  # Wikimedia asks for gentle downloads
nearest = min(p[4] for p in pics)
print(f"   the nearest any test photo comes to a training picture: {nearest} of 256 bits"
      f" (the same photo resized is under 10; two photos of one car are ~60+)")
if nearest <= 10:
    print("   SOME TEST PHOTO WAS TRAINED ON:", [p[0] for p in pics if p[4] <= 10])


def score(heads_):
    n = {"kind": 3, "side": 2, "colour": len(heads_["colour"].classes)}
    res = {w: [0, 0, 0, 0.0, 0.0] for w in n}          # strict right, lenient right, asked, guess strict, guess lenient
    lines = []
    for name, truth, im, f, _ in pics:
        a = H.read(heads_, card["paint"], f)
        marks = []
        for w in n:
            if not truth[w]:
                continue
            ok = truth[w].split("|")
            r = res[w]
            r[0] += a[w]["answer"] == ok[0]
            r[1] += a[w]["answer"] in ok
            r[2] += 1
            r[3] += 1 / n[w]
            r[4] += min(1, len(ok) / n[w])
            marks.append(f"{w} {a[w]['answer']}" + ("" if a[w]["answer"] == ok[0] else
                         " (fair)" if a[w]["answer"] in ok else f" (WRONG: {ok[0]})"))
        lines.append(f"   {name:22s} " + ", ".join(marks))
    return res, lines


res, lines = score(hs)
print(f"\n3. The trained model on {len(pics)} photos it never saw, against a person's answers")
print("\n".join(lines))
for w, (s, l, n, gs, gl) in res.items():
    c, k = collections.Counter(t[w].split("|")[0] for _, t, *_ in pics if t[w]).most_common(1)[0]
    print(f"   {w:6s}: strictly {s} of {n}, leniently {l} of {n}; random guessing would get about {gs:.0f} and"
          f" {gl:.0f}, always saying {c} {k}")

print("\n4. Controls")
rng = np.random.default_rng(1)
fake = {k: H.Head(h.classes, rng.normal(0, h.W.std(), h.W.shape), rng.normal(0, h.b.std() + 1e-3, h.b.shape))
        for k, h in hs.items()}
fres, _ = score(fake)
print("   the same code with the trained weights swapped for random ones:",
      ", ".join(f"{w} {s} of {n}" for w, (s, l, n, gs, gl) in fres.items()), "(guessing level: the skill is in the training)")
moved = asked = greyed = grey_asked = 0
for name, truth, im, f, _ in pics:
    a = H.read(hs, card["paint"], f)["colour"]["answer"]
    if a in H.NEUTRAL:
        continue                   # a white or grey car: recolouring it changes little
    p = card["paint"][a]
    want = H.shade_group({"swapped": "#" + p[5:7] + p[3:5] + p[1:3]}, "swapped")   # its paint, red and blue swapped
    r, g, b = im.split()
    s = H.read(hs, card["paint"], features(Image.merge("RGB", (b, g, r))))["colour"]["answer"]
    ok = H.shade_group(card["paint"], s) == want
    asked += 1
    moved += ok
    gs = H.read(hs, card["paint"], features(im.convert("L").convert("RGB")))["colour"]["answer"]
    grey_asked += 1
    greyed += gs in H.NEUTRAL
    print(f"   {name:22s} {a:11s} | red and blue swapped: {s:11s}{'' if ok else ' (did not move with it)'}"
          f" | turned grey: {gs}{'' if gs in H.NEUTRAL else ' (still a colour)'}")
print(f"   red and blue swapped, the paint moves with it: {moved} of {asked};"
      f" turned grey, the colour goes: {greyed} of {grey_asked}")
print("   (not a check: the side reading averages a picture with its mirror, so a mirror always reads the other way)")
noise = Image.fromarray(np.random.default_rng(0).integers(0, 256, (300, 450, 3), dtype=np.uint8))
n = H.read(hs, card["paint"], features(noise))
print(f"   random noise, no vehicle at all: it still answers {n['kind']['answer']} ({n['kind']['p']:.0%}):"
      " it cannot tell a vehicle from none (a known limit)")


def ask(prompt):
    try:
        return input(prompt).strip().lower()
    except (EOFError, OSError):
        return None


at_keys = "google.colab" in sys.modules or sys.stdin.isatty()
if BLIND and not at_keys:
    print("\n5. Blind test skipped: it needs you at the keyboard (run it in Colab or a terminal)")
elif BLIND:
    print(f"\n5. Blind test: {BLIND} photos picked at random now. Type what you see first (Enter to skip one)")
    agree = asked_b = 0
    words = ["car side view", "van", "motorcycle", "hatchback", "estate car", "pickup truck", "saloon car"]
    for i in range(BLIND):
        try:
            q = {"action": "query", "format": "json", "list": "search", "srnamespace": 6, "srlimit": 1,
                 "srsearch": random.choice(words) + " filetype:bitmap", "sroffset": random.randrange(0, 2000)}
            hit = json.loads(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(q)))["query"]["search"]
            title = hit[0]["title"]
            q = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 900}
            info = next(iter(json.loads(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(q)))["query"]["pages"].values()))
            url = info["imageinfo"][0]["thumburl"]
            im = photo(url)
        except Exception as e:
            print(f"   photo {i + 1}: could not fetch one ({e})")
            continue
        print(f"\n   photo {i + 1}: {title}\n   {url}")
        if "google.colab" in sys.modules:
            from IPython.display import display
            t = im.copy()
            t.thumbnail((480, 480))
            display(t)
        you = {w: ask(f"   your answer, {q}: ") for w, q in (("kind", "car, van or motorbike"), ("side", "points left or right"),
                                                             ("colour", "its paint (e.g. white, silver, red)"))}
        a = H.read(hs, card["paint"], features(im))
        print("   the model:", ", ".join(f"{w} {a[w]['answer']} ({a[w]['p']:.0%})" for w in ("kind", "side", "colour")))
        for w in you:
            if you[w]:
                asked_b += 1
                agree += you[w] == a[w]["answer"]
    if asked_b:
        print(f"\n   you and the model agreed on {agree} of {asked_b} answers")

if MY_PHOTO:
    try:
        a = H.read(hs, card["paint"], features(photo(MY_PHOTO)))
        print("\n6. Your photo:", ", ".join(f"{w} {a[w]['answer']} ({a[w]['p']:.0%})" for w in ("kind", "side", "colour")))
    except Exception as e:
        print(f"\n6. Your photo could not be read ({e}): use the address of the picture itself (ending .jpg or .png)")

s = card["held_out_scores"]
print(f"\nIts README's numbers, from {card['examples']['vehicles']} vehicles held out (the commonest answer always:"
      f" {', '.join(s[w + '_photo']['always_the_commonest']['answer'] for w in ('kind', 'side', 'colour'))}):")
for w in ("kind", "side", "colour"):
    print(f"   {w:6s} {s[w + '_photo']['right']:.0%}, against {s[w + '_photo']['always_the_commonest']['right']:.0%}")
cv = s["kind_photo"]["cars_and_vans"]
print(f"   cars and vans alone, kind {cv['right']:.0%}, against {cv['always_car']:.0%} always saying car;"
      f" colour to the next shade {s['colour_photo']['right_or_next_shade']:.0%}")

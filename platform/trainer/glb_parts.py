#!/usr/bin/env python3
"""Audit catalogue GLBs against the STRIP BAY STANDARD — the Mk8 Golf.

The trainer works on `volkswagen-golf-2021-w12-v1` because that asset is
SEPARABLE: four doors, a tailgate, four wheels, brakes, seats, steering
wheel, airbags and cabin trim all arrive as distinctly NAMED meshes, and
`golf-bay.html`'s `classify()` maps those names onto part groups. A car
whose body, doors and wheels are one welded shell cannot be taken apart,
so every teardown action silently does nothing — the exact failure the
app already shipped once (partIds 1 instead of 25, no error, a flawless
render of a car that would not come apart).

This tool answers, per asset: WOULD STRIP BAY WORK ON THIS CAR?

WHY IT IS CHEAP. A GLB is a 12-byte header, then a length-prefixed JSON
chunk, then the binary. Every node and mesh name is in that JSON, at the
FRONT of the file. So two HTTP Range requests read the whole name table
without pulling a 48 MB mesh: one for the 20-byte header, one for exactly
the JSON chunk. The catalogue's median asset is 10 MB and its largest is
48 MB; at 1,044 assets a full download is ~15 GB, which this box does not
have and which the standing order forbids keeping anyway.

TWO VERDICTS PER CAR, AND THE SECOND ONE EXISTS TO KEEP THE FIRST HONEST.

  STRICT — `golf-bay.html`'s RULES, copied verbatim. This is literally
    "does the app work on it today".
  BROAD  — a name-agnostic sweep for door/bonnet/boot/wheel/seat words in
    several languages and spellings, anchored nowhere.

Where STRICT finds nothing and BROAD finds parts, the car IS separable and
the app's rules simply do not know its naming convention — a fact about
the REGEX, not about the car. This project has already paid for that
confusion once: `TYRE_MAT` refused plurals, so a gate printed "no tyre
material in this car" about ten of sixty live cars when the truth was that
the pattern could not see `Tires`. Reporting only STRICT would repeat it.

WHAT THIS TOOL CANNOT TELL YOU, stated because a silent limit is worse
than a missing feature:

  * IT DOES NOT PROVE A DOOR OPENS. It proves a door is separately named
    and therefore addressable. Whether the hinge axis the app derives is
    sane, whether the door clips the body on the way out, and whether the
    door card and glass travel with it are questions for a render.
  * IT DOES NOT SCORE THE ENGINE, IT SEARCHES FOR ONE. CLAUDE.md records
    that engine, starter, battery, suspension and exhaust are absent from
    all 163 meshes of the reference Golf, which is why Strip Bay builds
    its engine in code. That was measured on ONE car and then quoted as
    though it were a property of the library. The BROAD sweep now looks
    for engine, suspension and exhaust words across every asset, so the
    claim becomes a measurement. A car that DOES ship an engine would be
    the most valuable asset here for this trainer, and it would be a
    shame to have owned one all along without looking.
  * A name is not a verdict on quality. Glazing, tyre colour and clay
    shells are separate gates that already exist.

Usage
-----
    python3 glb_parts.py --control          # the Mk8 Golf, alone
    python3 glb_parts.py --limit 40         # first 40 approved assets
    python3 glb_parts.py --all --out parts_audit.json
    python3 glb_parts.py --asset volkswagen-golf-mk8-v1
"""
import argparse, json, re, struct, sys, time, urllib.request, urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

CATALOGUE = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/"
             "public/car-renders/resolver/catalogue.v2.json")
CONTROL = "volkswagen-golf-2021-w12-v1"      # the asset the trainer is built on
UA = {"User-Agent": "strip-bay-audit/1.0"}   # urllib's default UA is refused by
                                             # some endpoints on this account

# ── the app's own rules, copied verbatim from golf-bay.html ──────────────
# Keep these in sync by COPYING, never by paraphrasing: a rule that drifts
# turns this audit into a measurement of the copy.
RULES = [
    (r'^Panel_Bonnet', 'panel_bonnet'),
    (r'^Asm_Mirror_FL', 'mirror_fl'),
    (r'^Ext_Door_FL_|^Int_Door_FL_|^Ext_Door_Limiter_FL', 'door_fl'),
    (r'^Ext_Door_FR_|^Int_Door_FR_|^Ext_Door_Limiter_FR', 'door_fr'),
    (r'^Ext_Door_RL_|^Int_Door_RL_|^Ext_Door_Limiter_RL', 'door_rl'),
    (r'^Ext_Door_RR_|^Int_Door_RR_|^Ext_Door_Limiter_RR', 'door_rr'),
    (r'^Ext_Trunk_Lid|^Int_Trunk_Lid', 'tailgate'),
    (r'^Rim_FL|^Tire_FL', 'wheel_fl'), (r'^Rim_FR|^Tire_FR', 'wheel_fr'),
    (r'^Rim_RL|^Tire_RL', 'wheel_rl'), (r'^Rim_RR|^Tire_RR', 'wheel_rr'),
    (r'^Ext_Brake_FL_Rotor', 'rotor_fl'), (r'^Ext_Brake_FR_Rotor', 'rotor_fr'),
    (r'^Ext_Brake_FL_Caliper', 'caliper_fl'), (r'^Ext_Brake_FR', 'caliper_fr'),
    (r'^Ext_Brake_Rear', 'brakes_rear'),
    (r'^Int_Airbag', 'airbags'), (r'^Int_Seats|^seat_', 'seats'),
    (r'^Int_SW', 'steering'),
    (r'^Ext_Sunroof', 'sunroof'), (r'^Ext_Lights', 'lamps_front'),
    (r'^Ext_Taillight', 'lamps_rear'),
    (r'^Ext_Window|^Int_Window|^Int_Body_Window|^Ext_Body_Window|^Int_Glass_Clear',
     'glazing'),
    (r'^Int_', 'cabin'), (r'.', 'body'),
]
RULES = [(re.compile(p), i) for p, i in RULES]


# ── CONVENTION 2, and it is NOT yet in the app ──────────────────────────
# The `G:Ext_Door_FL_…` naming the trainer is built on belongs to ONE
# supplier batch. A second, equally clean convention exists in the
# library — `mercedes-benz-e-class-w213` names its 90 meshes
# `mesh_DoorFL_mat_body_0`, `BrakeDiskFL`, `WheelFR`, `Hood`, `Trunk`,
# `SteeringWheel`. Every part Strip Bay needs is there under a different
# spelling, and that car is one regex away from working.
#
# Kept HERE rather than pasted straight into golf-bay.html so the value
# can be MEASURED first: `--rescue` scores the whole catalogue under both
# rulesets and says how many cars convention 2 actually buys. Widening a
# live classifier on the strength of one example is how the app got a
# catch-all that swallowed 163 meshes.
#
# Note `mesh_` and the `_mat_<material>_0` suffix are stripped before
# matching, because this exporter emits one mesh PER MATERIAL per part —
# `DoorFL` arrives as five meshes (body, chrome, glass, inside_panel,
# leather) and all five must land in the same group.
RULES2 = [
    (r'^Hood$|^Bonnet$', 'panel_bonnet'),
    (r'^MirrorL$|^MirrorFL$|^Mirror_L$', 'mirror_fl'),
    (r'^DoorFL$', 'door_fl'), (r'^DoorFR$', 'door_fr'),
    (r'^DoorRL$', 'door_rl'), (r'^DoorRR$', 'door_rr'),
    (r'^Trunk$|^Tailgate$|^Hatch$|^Boot$', 'tailgate'),
    (r'^WheelFL$|^TireFL$|^RimFL$', 'wheel_fl'),
    (r'^WheelFR$|^TireFR$|^RimFR$', 'wheel_fr'),
    (r'^WheelRL$|^TireRL$|^RimRL$', 'wheel_rl'),
    (r'^WheelRR$|^TireRR$|^RimRR$', 'wheel_rr'),
    (r'^BrakeDiskFL$|^BrakeDiscFL$|^RotorFL$', 'rotor_fl'),
    (r'^BrakeDiskFR$|^BrakeDiscFR$|^RotorFR$', 'rotor_fr'),
    (r'^BrakeFL$|^CaliperFL$', 'caliper_fl'),
    (r'^BrakeFR$|^CaliperFR$', 'caliper_fr'),
    (r'^BrakeRL$|^BrakeRR$|^BrakeDiskRL$|^BrakeDiskRR$', 'brakes_rear'),
    (r'^SteeringWheel$|^Steering_Wheel$', 'steering'),
    (r'^Seat|^Seats$', 'seats'),
    (r'^Gauge_|^Pedal|^Dash|^Interior|^Wipper|^Wiper', 'cabin'),
    (r'^Glass|^Window|^Windshield|^Windscreen', 'glazing'),
    (r'^Headlight|^Taillight|^Light', 'lamps_front'),
    (r'.', 'body'),
]
RULES2 = [(re.compile(p, re.I), i) for p, i in RULES2]
_MAT_SUFFIX = re.compile(r'_mat_.*$|_\d+$')


# ── CONVENTION 3 — THE SIM-MOD FAMILY, and it beats the Golf ────────────
# `volvo-xc90-v1` and `volkswagen-golf-gti-vw2-v1` name their parts
# `<car>_door_FL`, `<car>_hood`, `<car>_tailgate`, `<car>_seat_FL`,
# `<car>_engine_i4`, `<car>_turbo_i4`, `<car>_intercooler`,
# `<car>_transmission`, `<car>_driveshaft`, `<car>_lowerarm_F`,
# `<car>_spring_R`, `<car>_subframe_F`. That is a driving-sim vehicle mod,
# and it carries an ENGINE BAY, A DRIVELINE AND A SUSPENSION — none of
# which exist in the reference Golf at all. For a mechanics trainer this
# is a BETTER asset than the car the trainer was built on.
#
# TWO HONEST GAPS IN IT, found by reading the part list rather than
# assuming the richer car wins everything:
#   * THE FOUR WHEELS ARE INSTANCES, NOT CORNERS. They are `wheel_x`,
#     `wheel_x.001`, `.002`, `.003` and `tire`, `tire.001`… so no name
#     says which corner is which. "Take the front left wheel off" needs a
#     POSITION lookup here, where the Golf says `Rim_FL` outright.
#   * NO BRAKE DISCS OR CALIPERS. `pedal_brake_A` is the pedal. The brake
#     job cannot run on this family as it stands.
# Both are recorded rather than smoothed over, because a trainer that
# says "front left" while moving an arbitrary wheel teaches nothing.
RULES3 = [
    (r'^hood$|^bonnet$', 'panel_bonnet'),
    (r'^mirror_L(_base)?$', 'mirror_fl'),
    # door glass is named separately here; it travels WITH the door, the
    # same way `Ext_Door_FL_Glass` does under convention 1
    (r'^door_?glass_FL$|^door_FL', 'door_fl'),
    (r'^door_?glass_FR$|^door_FR', 'door_fr'),
    (r'^door_?glass_RL$|^door_RL', 'door_rl'),
    (r'^door_?glass_RR$|^door_RR', 'door_rr'),
    (r'^tailgate|^trunk|^boot_lid|^hatch', 'tailgate'),
    (r'^windshield|^windscreen|^sideglass|^rearglass|^backglass', 'glazing'),
    (r'^seat_[FR][LR]?|^seats?$', 'seats'),
    (r'^steeringwheel$|^steering_wheel', 'steering'),
    (r'^interior|^gauge|^speedo|^tacho|^needle_|^pedal_|^shifter|^ceiling'
     r'|^shelf|^signalstalk|^dash|^console|^carpet', 'cabin'),
    (r'^headlight|^headlamp', 'lamps_front'),
    (r'^taillight|^taillamp|^rearlight', 'lamps_rear'),
    # the parts the Golf simply does not have — scored so the gain is
    # visible rather than implied
    (r'^engine|^engbay|^intake|^intakecover|^turbo|^intercooler|^airbox'
     r'|^podfilter|^radiator|^radfan|^radsupport|^fueltank|^strut_bar'
     r'|^exhaust', 'engine'),
    (r'^transmission|^transfercase|^driveshaft|^halfshaft|^diff_'
     r'|^gearbox|^clutch', 'driveline'),
    (r'^lowerarm|^upperarm|^wishbone|^spring_|^shock_|^strut_front'
     r'|^swaybar|^subframe|^tierod|^trailingarm|^rearbeam|^hub_[FR]'
     r'|^tubs_|^tray_', 'suspension'),
    (r'^wheel|^tire|^tyre|^rim', 'wheels_unsided'),   # instanced, see above
    (r'.', 'body'),
]
RULES3 = [(re.compile(p, re.I), i) for p, i in RULES3]
# this family suffixes every mesh with its material and an instance index
_C3_STRIP = re.compile(
    r'(?:[._]\d+)+$|_(?:vivace|etk\w*|bastion|gmk\d|usdm|jdm)\w*$', re.I)


def classify3(n, prefix=''):
    base = n
    if prefix and base.lower().startswith(prefix.lower()):
        base = base[len(prefix):]
    for _ in range(3):                       # suffixes stack: `.001_x_black`
        nb = _C3_STRIP.sub('', base)
        if nb == base:
            break
        base = nb
    base = base.strip('_. ')
    for rx, pid in RULES3:
        if rx.match(base):
            return pid
    return 'body'


def c3_prefix(names):
    """This family prefixes EVERY mesh with the car's own short name —
    `xc90_`, `w177_`, `pab_v55_`. Find it as the commonest leading token
    rather than hard-coding one, or the rules match nothing."""
    heads = Counter()
    for n in names:
        m = re.match(r'^([a-z0-9]{2,12}_)', n, re.I)
        if m:
            heads[m.group(1).lower()] += 1
    if not heads:
        return ''
    top, cnt = heads.most_common(1)[0]
    return top if cnt >= max(6, len(names) * 0.25) else ''


_MAT_TOKEN = re.compile(r'_mat_(.+?)_\d+$')


def classify2(n):
    """Convention 2. Strips the exporter's `mesh_` prefix and `_mat_x_0`
    suffix, then matches ANCHORED names — anchored on purpose, so `Body`
    cannot be caught by a loose /door/ and a `Door_Handle` cannot be
    mistaken for the door itself.

    GLAZING IS IN THE MATERIAL TOKEN, NOT THE PART NAME. This exporter
    splits one part into one mesh per material, so the windscreen is
    `mesh_Body_mat_glass_0` and there is no part called `Glass` anywhere.
    Read the material token and route BODY glass to `glazing` — but leave
    DOOR glass on its door, which is both what conv 1 does (the door rule
    precedes the glazing rule, so `Ext_Door_FL_Glass` is door_fl) and
    what is physically right: the glass goes with the door when the door
    comes off.
    """
    mat = _MAT_TOKEN.search(n)
    base = _MAT_SUFFIX.sub('', re.sub(r'^mesh_', '', n)).strip()
    pid = 'body'
    for rx, p in RULES2:
        if rx.match(base):
            pid = p
            break
    if mat and pid == 'body' and re.search(r'glass|window', mat.group(1), re.I):
        return 'glazing'
    return pid


def classify(n):
    """golf-bay.html's classify(), including the colon workaround.

    three.js's PropertyBinding.sanitizeNodeName STRIPS the colon from
    `G:Ext_Door_FL_…`, so the app has to match the raw name and both
    de-prefixed forms. Reading names straight out of the glTF JSON there
    is no sanitiser in the way — but the same three candidates are tried
    here anyway, because the point is to reproduce what the APP sees.
    """
    cands = [n]
    if n.startswith('G:'):
        cands.append(n[2:])
    if re.match(r'^G[A-Z]', n):
        cands.append(n[1:])
    for rx, pid in RULES:
        for c in cands:
            if rx.search(c):
                return pid
    return 'body'


# ── the broad, naming-agnostic sweep ────────────────────────────────────
# Deliberately multilingual and spelling-tolerant. Sourced assets come
# from uploaders worldwide and this project has already lost real cars to
# a pattern that assumed one spelling (CR-V vs CRV, Tires vs Tire, a
# Portuguese "Roda" that is a wheel). Anchored NOWHERE, matched
# case-insensitively, on the whole name.
BROAD = {
    'door':     r'door|puerta|porta|tuer|tür|portiere|dver',
    'bonnet':   r'bonnet|hood|capot|capo|motorhaube|cofano',
    'tailgate': r'tailgate|trunk|boot(?!s)|hatch|liftgate|decklid|maletero|kofferraum|portellone',
    'wheel':    r'wheel|rim|tyre|tire|rueda|roda|jante|felge|cerchio|llanta|reifen|pneu',
    'seat':     r'seat|siege|siège|asiento|sitz|sedile|banco',
    'steering': r'steering|steer_?wheel|volante|lenkrad|volant',
    'interior': r'interior|cabin|dash|dashboard|cockpit|innenraum|salpicadero|tablero',
    'glass':    r'glass|window|windscreen|windshield|glazing|vidro|glas|scheibe|fenster|cristal',
    'lamp':     r'headlight|headlamp|taillight|tail_?lamp|rearlight|faro|scheinwerfer|phare',
    'mirror':   r'mirror|retrovisor|spiegel|rétroviseur|specchi',
    # ASKED FOR EXPLICITLY, and expected to be EMPTY on every row.
    # CLAUDE.md records that engine, starter, battery, suspension and
    # exhaust are absent from all 163 meshes of the reference Golf, and
    # Strip Bay constructs its engine in code. That was measured on ONE
    # car. Sweeping for it across the whole library turns a quoted claim
    # into a measurement — and if any car DOES ship an engine, that is
    # the single most valuable asset in the catalogue for this trainer.
    'engine':   r'engine|motor(?!way|cycle)|cylinder|piston|crank|camshaft|'
                r'manifold|turbo|intercooler|radiator|moteur|motore',
    'suspension': r'suspension|damper|shock_?abs|strut|spring|wishbone|'
                  r'control_?arm|subframe|axle',
    'exhaust':  r'exhaust|muffler|silencer|tailpipe|downpipe|catalyt',
}
# WORDS THAT LOOK LIKE PARTS AND ARE NOT. `boot` is the trap that forced
# this list: a "Boot" on a driver figure or a gearstick gaiter is not a
# tailgate. Checked before a BROAD hit is counted.
BROAD_TRAPS = re.compile(
    r'gaiter|gearstick|gear_?lever|shift_?boot|footwell|bootlace|'
    r'reboot|bootstrap|door_?handle_?only', re.I)
BROAD = {k: re.compile(v, re.I) for k, v in BROAD.items()}

# The groups the trainer's jobs actually need, and which bay needs each.
# An asset missing any of these cannot run that bay.
NEEDED = {
    'doors':    (['door_fl', 'door_fr', 'door_rl', 'door_rr'], 'Strip / Door off / Inside a door'),
    'tailgate': (['tailgate'], 'Strip'),
    'wheels':   (['wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr'], 'Strip / Brake job'),
    'brakes':   (['rotor_fl', 'caliper_fl'], 'Brake job'),
    'interior': (['cabin', 'seats', 'steering'], 'Interior'),
    'glazing':  (['glazing'], 'Strip'),
}
# NOT in NEEDED, on purpose:
#   panel_bonnet — the bonnet is NOT a separate mesh in any sourced car.
#     It is cut out of the welded body shell by panel_cut.py as a
#     post-process. Its absence is the NORMAL state of a fresh asset and
#     scoring it as a failure would fail every car including the control
#     before the cut is applied. Reported separately as `bonnet_cut`.
#   mirror_fl — same: cut out of the door meshes by panel_cut.py.
#   engine — absent from every car file in this catalogue (see the note
#     at the top). Strip Bay builds one.


def fetch(url, start=None, end=None, timeout=60, tries=5):
    """GET, with backoff on throttling.

    A 429 IS NOT A PROPERTY OF THE ASSET, and the first full run recorded
    52 of them as `ERROR` rows indistinguishable from a corrupt file. At
    eight workers the storage endpoint throttles; the fix is to back off
    and retry rather than to report someone else's rate limit as a fact
    about their car. 503 and 500 are retried for the same reason.
    """
    delay = 2.0
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=dict(UA))
        if start is not None:
            req.add_header('Range', f'bytes={start}-{end}')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.status
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                # honour Retry-After when the server states one
                ra = e.headers.get('Retry-After') if e.headers else None
                time.sleep(float(ra) if (ra or '').isdigit() else delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError('unreachable')


def glb_json(url):
    """Read a GLB's glTF JSON chunk over HTTP Range. Two small requests.

    Returns (parsed_json, bytes_read). Raises on anything that is not a
    well-formed GLB — a truncated file, an unpacked .gltf served under a
    .glb name (the recorded gltf-transform trap), or an HTML error page.
    """
    head, _ = fetch(url, 0, 19)
    if len(head) < 20:
        raise ValueError(f'short read: {len(head)} bytes (not a GLB)')
    magic, ver, _total, jlen, jtype = struct.unpack('<IIIII', head[:20])
    if magic != 0x46546C67:                       # 'glTF'
        raise ValueError('no glTF magic — unpacked .gltf or an error page')
    if jtype != 0x4E4F534A:                       # 'JSON'
        raise ValueError('first chunk is not JSON')
    if jlen > 64 * 1024 * 1024:
        raise ValueError(f'implausible JSON chunk: {jlen} bytes')
    body, _ = fetch(url, 20, 20 + jlen - 1)
    return json.loads(body[:jlen].decode('utf-8')), 20 + len(body)


def audit_one(asset):
    """One asset -> one row. Never raises; a failure is a row with an error."""
    url = asset.get('desktopGlbUrl')
    row = {'assetId': asset.get('assetId'), 'make': asset.get('make'),
           'model': asset.get('model'), 'sourceTitle': asset.get('sourceTitle'),
           'url': url}
    if not url:
        row['error'] = 'no desktopGlbUrl'
        return row
    try:
        g, nbytes = glb_json(url)
    except urllib.error.HTTPError as e:
        row['error'] = f'HTTP {e.code}'
        return row
    except Exception as e:
        row['error'] = f'{type(e).__name__}: {e}'
        return row

    # Every name the app could classify: nodes carry the names the app
    # reads (o.name), meshes are included because a node may be unnamed
    # and inherit from its mesh.
    names = [n.get('name', '') for n in g.get('nodes', [])]
    names += [m.get('name', '') for m in g.get('meshes', [])]
    names = [n for n in names if n]

    groups = Counter(classify(n) for n in names)
    # score convention 2 alongside, never instead — see RULES2
    g2 = Counter(classify2(n) for n in names)
    row['groups2'] = dict(sorted(g2.items()))
    row['strict2'] = {k: f'{len([i for i in ids if i in g2])}/{len(ids)}'
                      for k, (ids, _b) in NEEDED.items()}
    row['strict2Pass'] = all(all(i in g2 for i in ids)
                             for ids, _b in NEEDED.values())
    pre = c3_prefix(names)
    g3 = Counter(classify3(n, pre) for n in names)
    row['c3prefix'] = pre
    row['groups3'] = dict(sorted(g3.items()))
    row['strict3'] = {k: f'{len([i for i in ids if i in g3])}/{len(ids)}'
                      for k, (ids, _b) in NEEDED.items()}
    # the three things convention 3 has that the Golf does not
    row['extras3'] = [k for k in ('engine', 'driveline', 'suspension')
                      if k in g3]
    row['bytesRead'] = nbytes
    row['nodes'] = len(g.get('nodes', []))
    row['meshes'] = len(g.get('meshes', []))
    row['materials'] = len(g.get('materials', []))
    row['named'] = len(names)
    row['groups'] = dict(sorted(groups.items()))
    row['groupCount'] = len(groups)
    row['bonnet_cut'] = 'panel_bonnet' in groups     # panel_cut.py applied?
    row['mirror_cut'] = 'mirror_fl' in groups

    have = {}
    for label, (ids, _bay) in NEEDED.items():
        have[label] = [i for i in ids if i in groups]
    row['strict'] = {k: f'{len(v)}/{len(NEEDED[k][0])}' for k, v in have.items()}
    row['strictPass'] = all(len(v) == len(NEEDED[k][0]) for k, v in have.items())
    row['missing'] = [f'{k} ({NEEDED[k][1]})'
                      for k, v in have.items() if len(v) < len(NEEDED[k][0])]

    broad = {}
    for label, rx in BROAD.items():
        hits = [n for n in names if rx.search(n) and not BROAD_TRAPS.search(n)]
        if hits:
            broad[label] = len(hits)
    row['broad'] = broad
    # The row that matters most: the app sees nothing, but the car plainly
    # HAS parts under another naming convention.
    row['separableUnknownNaming'] = (not row['strictPass']
                                     and len(broad) >= 4
                                     and 'door' in broad and 'wheel' in broad)

    # ── JUNK NAMES ARE A THIRD CATEGORY, AND THE FIRST SWEEP MISSED IT ──
    # `volkswagen-polo-2023-v1` has 114 separate meshes all called
    # `Object_10`, `Object_100`, …  That car is NOT a fused shell — the
    # geometry is split, and splitting is the expensive part — but it is
    # not addressable BY NAME either, so no amount of widening the regex
    # reaches it. Lumping it in with a 7-mesh Tesla (genuinely welded)
    # would have pointed the next piece of work at the wrong problem
    # entirely: one needs a geometric classifier, the other needs
    # segmentation or a different source.
    JUNK = re.compile(r'^(object|mesh|node|polysurface|group|shell|'
                      r'pasted_+\w*|defaultmaterial|untitled|material)'
                      r'[_\-\s.#]*\d*$|^\w*polysurface\d+', re.I)
    real = [n for n in names if not JUNK.match(n.strip())]
    row['namedFrac'] = round(len(real) / len(names), 3) if names else 0.0
    row['sampleNames'] = names[:6]

    # Few meshes AND no part words = one welded solid.
    row['fusedShell'] = (len(broad) <= 1 and row['meshes'] <= 8)
    # Plenty of meshes, but nothing in them a human named.
    row['unnamed'] = (not row['fusedShell'] and len(broad) == 0)
    return row


def verdict(row):
    if 'error' in row:
        return 'ERROR'
    if row['strictPass']:
        return 'GOLF STANDARD'
    if row.get('strict2Pass'):
        return 'GOLF STANDARD (conv 2)'
    if row['separableUnknownNaming']:
        return 'separable, other naming'
    if row['fusedShell']:
        return 'FUSED SHELL'
    if row['unnamed']:
        return 'split but UNNAMED'
    return 'partial'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--asset', help='one assetId')
    ap.add_argument('--control', action='store_true',
                    help='the Mk8 Golf the trainer is built on, alone')
    ap.add_argument('--status', default='approved')
    ap.add_argument('--out')
    ap.add_argument('--jobs', type=int, default=4,
                    help='parallel fetchers; see the note in main()')
    ap.add_argument('--resume', action='store_true',
                    help='skip assets already present in --out')
    a = ap.parse_args()

    cat = json.loads(fetch(CATALOGUE)[0].decode('utf-8'))
    pool = [x for x in cat if x.get('publicationStatus') == a.status]
    if a.control:
        pool = [x for x in cat if x.get('assetId') == CONTROL]
    elif a.asset:
        pool = [x for x in cat if x.get('assetId') == a.asset]
    elif not a.all:
        pool = pool[:a.limit]

    done = {}
    if a.resume and a.out:
        try:
            done = {r['assetId']: r for r in json.load(open(a.out))}
        except Exception:
            pass

    todo = [x for x in pool if x.get('assetId') not in done]
    rows = [done[x['assetId']] for x in pool if x.get('assetId') in done]

    # FOUR WORKERS. Each asset is two small Range requests, so this is
    # latency-bound, not bandwidth-bound: serially it measured ~6 assets a
    # minute, i.e. three hours for the catalogue. EIGHT was tried and the
    # endpoint threw 429 at 52 of the first 471 — measured, not feared —
    # so the default came down and `fetch` grew a backoff. The ceiling is
    # deliberate either way: this is someone else's storage endpoint and
    # the job is an audit, not a load test.
    def work(item):
        i, asset = item
        r = audit_one(asset)
        v = verdict(r)
        extra = (r.get('error') or
                 f"groups {r['groupCount']:>2}  meshes {r['meshes']:>4}  "
                 f"{'  '.join(k + ' ' + s for k, s in r['strict'].items())}")
        print(f'{i:>4}/{len(pool)}  {v:<24} {asset.get("assetId"):<46} {extra}',
              flush=True)
        return r

    if a.jobs > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            for n, r in enumerate(ex.map(work, enumerate(todo, 1)), 1):
                rows.append(r)
                if a.out and n % 25 == 0:
                    json.dump(rows, open(a.out, 'w'), indent=1)
    else:
        for item in enumerate(todo, 1):
            rows.append(work(item))
            if a.out and len(rows) % 10 == 0:
                json.dump(rows, open(a.out, 'w'), indent=1)

    if a.out:
        json.dump(rows, open(a.out, 'w'), indent=1)
    print('\n' + '─' * 70)
    for v, n in Counter(verdict(r) for r in rows).most_common():
        print(f'{n:>5}  {v}')
    mb = sum(r.get('bytesRead', 0) for r in rows) / 1e6
    print(f'\nread {mb:.1f} MB over {len(rows)} assets '
          f'(full download would be tens of GB)')


if __name__ == '__main__':
    sys.exit(main())

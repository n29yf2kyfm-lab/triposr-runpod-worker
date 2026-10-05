#!/usr/bin/env python3
"""Propose a bodyStyle for approved catalogue cars that have none, from their
own published poster. A PROPOSAL only: nothing in the catalogue is changed.

    python3 platform/catalogue/propose_body_style.py OUT.csv [--workers=4]

Two independent vision models read each poster (Qwen3-VL 235B and Gemini 2.5
Flash, both via OpenRouter on OPENROUTER_API_KEY). A style is proposed only
when both name the same one; any disagreement or "unsure" is marked REVIEW for
a person to look at. The source title is recorded as well, and where it names
a body style that contradicts the models the row is also marked REVIEW.

Calibrated 2026-10-05 against 30 approved cars whose bodyStyle is already set:
Qwen 28/30, Gemini 29/30, and their misses never overlapped (Qwen: a 1992 NSX
read as convertible, the W168 A-Class as an MPV; Gemini: the A5 Sportback as
a coupe). Under the agree-or-review rule that sample gives 27 proposals, all
correct, and 3 reviews. A body style decides a HARD gate in the resolver (a
conflict rejects the car), so a wrong one makes a car unavailable: review the
proposals before writing any of them back.

Resumable: assetIds already in OUT.csv are skipped.
"""
import concurrent.futures as cf, csv, json, os, re, sys, tempfile, threading, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pipeline', 'machine'))
import ox                                       # noqa: E402

CAT = 'https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/resolver/catalogue.v2.json'
MODELS = ['qwen/qwen3-vl-235b-a22b-instruct', 'google/gemini-2.5-flash']
STYLES = ['hatchback', 'saloon', 'estate', 'suv', 'coupe', 'convertible', 'mpv', 'pickup', 'van']
Q = ("Look at this car. Reply with exactly one word from this list, the body style you can SEE: "
     + ', '.join(STYLES) + ". If you cannot tell, reply unsure.")
TITLE = [('estate', r'\b(estate|wagon|avant|touring|sportwagon|kombi|shooting ?brake|sw)\b'),
         ('convertible', r'\b(convertible|cabrio(let)?|roadster|spyder|spider|volante)\b'),
         ('coupe', r'\b(coupe|coupé)\b'), ('saloon', r'\b(saloon|sedan)\b'),
         ('hatchback', r'\b(hatch(back)?|3-?door|5-?door|3dr|5dr)\b'),
         ('suv', r'\b(suv|crossover)\b'), ('mpv', r'\b(mpv|minivan)\b'),
         ('pickup', r'\b(pick-?up|double cab|single cab|crew cab)\b'), ('van', r'\bvan\b')]
TITLE = [(k, re.compile(p, re.I)) for k, p in TITLE]
COLS = ['assetId', 'make', 'model', 'sourceTitle', 'qwen', 'gemini', 'title_says', 'proposal', 'action', 'posterUrl']
lock = threading.Lock()


def read(model, img):
    try:
        r = ox.ask(Q, model=model, max_tokens=4000, images=[img])
        txt = ((r.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
    except SystemExit as e:                     # ox exits on a hard HTTP error
        return f'error: {str(e)[:60]}'
    m = re.findall('|'.join(STYLES + ['unsure']), txt.lower())
    return m[0] if m else 'unreadable'


def one(e, out):
    d = tempfile.mkdtemp(prefix='body_')
    img = os.path.join(d, 'p.jpg')
    try:
        urllib.request.urlretrieve(e['posterUrl'], img)
        q, g = read(MODELS[0], img), read(MODELS[1], img)
    finally:
        try:
            os.remove(img)
        except OSError:
            pass
        os.rmdir(d)
    title = e.get('sourceTitle') or ''
    t = [k for k, rx in TITLE if rx.search(title)]
    agree = q == g and q in STYLES
    clash = agree and t and q not in t
    row = {'assetId': e['assetId'], 'make': e.get('make'), 'model': e.get('model'), 'sourceTitle': title,
           'qwen': q, 'gemini': g, 'title_says': ' '.join(t), 'proposal': q if agree else '',
           'action': 'REVIEW (title disagrees)' if clash else 'propose' if agree else 'REVIEW (models disagree)',
           'posterUrl': e['posterUrl']}
    with lock:
        new = not os.path.exists(out)
        with open(out, 'a', newline='') as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerow(row)
    return row


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(pos) != 1:
        print(__doc__)
        return 1
    out = pos[0]
    done = {r['assetId'] for r in csv.DictReader(open(out))} if os.path.exists(out) else set()
    cat = json.loads(urllib.request.urlopen(CAT, timeout=60).read())
    todo = [e for e in cat if e.get('publicationStatus') == 'approved' and not e.get('bodyStyle')
            and e.get('posterUrl') and e['assetId'] not in done]
    print(f'BODY {len(done)} done, {len(todo)} to go', flush=True)
    with cf.ThreadPoolExecutor(int(opt.get('workers', 4))) as ex:
        for i, r in enumerate(ex.map(lambda e: one(e, out), todo), 1):
            print(f"BODY [{i}/{len(todo)}] {r['action'][:6]:6s} {r['qwen']:11s} {r['gemini']:11s} {r['assetId']}", flush=True)
    rows = list(csv.DictReader(open(out)))
    print('BODY_DONE', {a: sum(1 for r in rows if r['action'] == a) for a in sorted({r['action'] for r in rows})}, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Write owner-approved bodyStyle proposals into the live v2 catalogue.

    python3 platform/catalogue/apply_body_styles.py PROPOSALS.csv            # dry run (default)
    python3 platform/catalogue/apply_body_styles.py PROPOSALS.csv --apply    # needs SB_KEY

Only rows whose action is `propose` are used, and only on an approved entry
whose bodyStyle is STILL empty in the live file — an existing value is never
overwritten, and a REVIEW row is never written. Each change records where it
came from in `bodyStyleEvidence`.

--apply, in this order, refusing at the first failure:
  1. back up the live file to car-renders/backups/catalogue.v2-<stamp>.json
  2. prove the backup fetches (200, byte-identical) — an upload 200 is not proof
  3. upload the patched catalogue
  4. re-fetch the live file and check every intended change is there and
     nothing else moved
and prints the one-line revert.

Approved by the owner 2026-10-06 ("1" = apply the 462 agreed proposals).
"""
import csv, datetime, hashlib, json, os, sys, urllib.request

REF = 'tfkvthprsntexrcuqpyd'
BASE = f'https://{REF}.supabase.co/storage/v1/object'
LIVE = 'resolver/catalogue.v2.json'


def env_key():
    k = os.environ.get('SB_KEY')
    if not k and os.path.exists('/root/.alam3d_env'):     # tools load the key themselves
        for line in open('/root/.alam3d_env'):
            if line.startswith('SB_KEY='):
                k = line.split('=', 1)[1].strip().strip('"\'')
    return k


def get(path):
    url = f'{BASE}/public/car-renders/{path}?cb={int(datetime.datetime.now().timestamp())}'
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def put(path, data, key):
    rq = urllib.request.Request(f'{BASE}/car-renders/{path}', data=data, method='POST')
    for h, v in (('apikey', key), ('Authorization', 'Bearer ' + key),
                 ('Content-Type', 'application/json'), ('x-upsert', 'true')):
        rq.add_header(h, v)
    with urllib.request.urlopen(rq, timeout=120) as r:
        return r.status


def patch(cat, rows, stamp):
    want = {r['assetId']: r for r in rows if r['action'] == 'propose' and r['proposal']}
    changed, skipped = [], []
    for e in cat:
        r = want.get(e.get('assetId'))
        if not r:
            continue
        if e.get('publicationStatus') != 'approved' or e.get('bodyStyle'):
            skipped.append((e['assetId'], e.get('publicationStatus'), e.get('bodyStyle')))
            continue
        e['bodyStyle'] = r['proposal']
        e['bodyStyleEvidence'] = (f"read from this asset's poster by two vision models that agreed "
                                  f"(qwen3-vl, gemini-2.5-flash); proposed 2026-10-05, owner-approved {stamp}")
        changed.append((e['assetId'], r['proposal']))
    return changed, skipped


def main():
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith('--')]
    if len(pos) != 1:
        print(__doc__)
        return 1
    rows = list(csv.DictReader(open(pos[0])))
    raw = get(LIVE)
    cat = json.loads(raw)
    before = {e['assetId']: json.dumps(e, sort_keys=True) for e in cat}
    stamp = datetime.date.today().isoformat()
    changed, skipped = patch(cat, rows, stamp)
    print(f'{len(cat)} entries | {len(changed)} would gain a bodyStyle | {len(skipped)} skipped '
          f'(no longer approved, or already has one)')
    for a, s in skipped[:10]:
        print('   skip', a, s)
    body = json.dumps(cat, indent=1, ensure_ascii=False).encode()
    if '--apply' not in args:
        out = os.path.join(os.path.dirname(os.path.abspath(pos[0])), 'catalogue.v2.patched.json')
        open(out, 'wb').write(body)
        print('DRY RUN. Patched copy written to', out, '— nothing uploaded.')
        return 0
    key = env_key()
    if not key:
        sys.exit('SB_KEY is not set and is not in /root/.alam3d_env — nothing written.')
    bak = f'backups/catalogue.v2-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
    put(bak, raw, key)
    if hashlib.sha256(get(bak)).hexdigest() != hashlib.sha256(raw).hexdigest():
        sys.exit(f'backup {bak} does not fetch back byte-identical — refusing to overwrite the live file')
    print('backed up live file ->', bak, '(verified)')
    put(LIVE, body, key)
    live = json.loads(get(LIVE))
    after = {e['assetId']: e for e in live}
    want = dict(changed)
    bad = [a for a, s in want.items() if after.get(a, {}).get('bodyStyle') != s]
    moved = [a for a, e in after.items() if a not in want and json.dumps(e, sort_keys=True) != before.get(a)]
    if bad or moved or len(after) != len(before):
        sys.exit(f'VERIFY FAILED: {len(bad)} missing changes, {len(moved)} unintended, '
                 f'{len(after)} vs {len(before)} entries. Revert: re-upload {bak} to {LIVE}')
    print(f'APPLIED and verified: {len(want)} bodyStyles live, nothing else moved.')
    print(f'Revert: upload car-renders/{bak} back to car-renders/{LIVE}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Move pictures a staged run has finished into the repo and commit them.

    PIC_STAGE=/some/dir python3 pic_sync.py [--loop=SECONDS]

illustrate.py and car_images.py write into $PIC_STAGE/illustrations and
$PIC_STAGE/cars when PIC_STAGE is set. This moves every finished .webp into
illustrations/ and cars/, copies cars/index.json across, then commits and pushes,
so the repo's working tree is only dirty for the second it takes to commit.
"""
import glob, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
STAGE = os.environ['PIC_STAGE']


def sync():
    n = 0
    for sub in ('illustrations', 'cars'):
        for f in glob.glob(os.path.join(STAGE, sub, '*.webp')):
            if time.time() - os.path.getmtime(f) < 5:      # still being written
                continue
            shutil.move(f, os.path.join(HERE, sub, os.path.basename(f)))
            n += 1
    ip = os.path.join(STAGE, 'cars', 'index.json')
    if os.path.exists(ip):
        shutil.copyfile(ip, os.path.join(HERE, 'cars', 'index.json'))
    if not n:
        return 0
    subprocess.run(['git', 'add', os.path.join(HERE, 'illustrations'), os.path.join(HERE, 'cars')], cwd=REPO)
    r = subprocess.run(['git', 'commit', '-qm', f'Pictures: {n} more AI part and car illustrations\n\n'
                        'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n'
                        'Claude-Session: https://claude.ai/code/session_01WhuBPFH24hTfC3LJVPmD1c'], cwd=REPO)
    if r.returncode == 0:
        subprocess.run(['git', 'push', '-q', 'origin', 'HEAD'], cwd=REPO)
    print(f'PIC_SYNC {n} pictures committed', flush=True)
    return n


if __name__ == '__main__':
    loop = int(dict(a[2:].split('=', 1) for a in sys.argv[1:] if '=' in a).get('loop', 0))
    while True:
        sync()
        if not loop:
            break
        time.sleep(loop)

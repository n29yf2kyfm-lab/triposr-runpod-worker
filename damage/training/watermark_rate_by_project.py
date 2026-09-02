"""Per-project watermark contamination rate.

OCR recall on a hand-labelled set is 30%, so a per-image verdict is not
trustworthy. A per-project RATE still is: the same detector is applied to
every project, so projects can be ranked against each other even though each
individual number understates the truth by roughly a factor of three.
"""
import sys, json, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, ".")
import wm_ocr

pairs = [l.rstrip("\n").split("\t") for l in open("wm_bysrc.txt")]
res = collections.defaultdict(lambda: [0, 0])          # project -> [hits, n]
with ThreadPoolExecutor(max_workers=3) as ex:
    for (src, _), r in zip(pairs, ex.map(lambda p: wm_ocr.read(p[1]), pairs)):
        res[src][1] += 1
        if r.get("hits"):
            res[src][0] += 1

out = sorted(res.items(), key=lambda kv: -kv[1][0] / max(1, kv[1][1]))
print(f"{'project':52}{'hit':>5}{'n':>5}{'rate':>7}")
for src, (h, n) in out:
    print(f"{src[:50]:52}{h:5}{n:5}{h/n*100:6.0f}%")
json.dump({k: v for k, v in res.items()}, open("wm_bysrc.json", "w"), indent=1)

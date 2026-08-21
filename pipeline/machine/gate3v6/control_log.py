#!/usr/bin/env python3
"""control_log.py -- render selftest.json as the negative-control log table."""
import json
import sys

d = json.load(open(sys.argv[1]))
print("| # | Check | Injected defect | Clean reading | Injected reading | Fires? |")
print("|---|---|---|---|---|---|")
n = 0
for k, v in d.items():
    if k.startswith("_") or not isinstance(v, dict):
        continue
    n += 1
    inj = v.get("injection", "")
    nums = {a: b for a, b in v.items()
            if a not in ("injection", "control_ok", "note", "finding")}
    keys = list(nums)
    clean = "; ".join(f"{a}={nums[a]}" for a in keys[:len(keys) // 2 or 1])
    bad = "; ".join(f"{a}={nums[a]}" for a in keys[len(keys) // 2 or 1:])
    ok = "YES" if v.get("control_ok") else "**NO**"
    print(f"| {n} | `{k}` | {inj} | {clean} | {bad} | {ok} |")
print()
print("Summary:", json.dumps(d.get("_summary")))

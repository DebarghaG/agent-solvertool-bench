"""Summarize stitch.py results: agent-visible time per proof, per step, and agreement between modes."""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path

d = Path(__file__).parent / "results"
runs = {p.stem: json.load(open(p))["results"] for p in sorted(d.glob("*.json"))}
tasks = {t["task"]: t for t in json.load(open(Path(__file__).parent / "tasks.json")) for t in [
    dict(t, task=f"{t['project']}/{t['file']}:{t['theorem']}")]}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


print(f"{'run':14} {'proofs':>6} {'failed':>6} {'steps':>5} {'open':>8} {'steps s':>9} {'final':>8} "
      f"{'total':>9} {'step med':>9} {'step p90':>9} {'step max':>9}")
for name, rs in runs.items():
    ok = [r for r in rs if "error" not in r]
    steps = [s["wall"] for r in ok for s in r["steps"]]
    print(f"{name:14} {len(ok):6} {len(rs) - len(ok):6} {len(steps):5} {sum(r['open'] for r in ok):8.1f} "
          f"{sum(steps):9.1f} {sum(r['final_check'] for r in ok):8.1f} {sum(r['total'] for r in ok):9.1f} "
          f"{st.median(steps):9.2f} {pct(steps, .9):9.2f} {max(steps):9.2f}")

common = set.intersection(*({r["task"] for r in rs if "error" not in r} for rs in runs.values()))
print(f"\nper project, mean seconds per step (over {len(common)} proofs every run completed)")
byp = defaultdict(lambda: defaultdict(list))
for name, rs in runs.items():
    for r in rs:
        if r["task"] in common:
            byp[r["task"].split("/")[0]][name] += [s["wall"] for s in r["steps"]]
print(f"{'project':24}" + "".join(f"{n:>14}" for n in runs))
for proj, m in byp.items():
    print(f"{proj:24}" + "".join(f"{st.mean(m[n]):14.2f}" for n in runs))

if "lsp" in runs and "beam-handle" in runs:
    print("\nlean-lsp-mcp step time vs source lines after the theorem (common proofs)")
    rows = []
    lsp = {r["task"]: r for r in runs["lsp"]}
    bh = {r["task"]: r for r in runs["beam-handle"]}
    for k in common:
        after = tasks[k]["file_lines"] - tasks[k]["proof_end"]
        rows.append((after, st.mean(s["wall"] for s in lsp[k]["steps"]),
                     st.mean(s["wall"] for s in bh[k]["steps"])))
    for lo, hi in ((0, 100), (100, 500), (500, 1500), (1500, 10**9)):
        b = [r for r in rows if lo <= r[0] < hi]
        if b:
            print(f"  {lo:>5}-{hi if hi < 10**9 else '':<5} lines after: n={len(b):2}  lsp {st.mean(r[1] for r in b):6.2f}s/step"
                  f"  beam-handle {st.mean(r[2] for r in b):5.2f}s/step")

    print("\nper-attempt agreement with lean-lsp-mcp (local line result), common proofs")
    for name in runs:
        if name == "lsp":
            continue
        other = {r["task"]: r for r in runs[name]}
        same = total = 0
        diffs = []
        for k in common:
            for sl, so in zip(lsp[k]["steps"], other[k]["steps"]):
                for al, ao in zip(sl["attempts"], so["attempts"]):
                    if al["ok"] is None or ao["ok"] is None:
                        continue
                    total += 1
                    same += al["ok"] == ao["ok"]
                    if al["ok"] != ao["ok"]:
                        diffs.append((k.split(":")[-1], al["text"][:40], al["ok"], ao["ok"]))
        print(f"  {name:12} {same}/{total}")
        for x in diffs[:8]:
            print(f"    differ: {x}")

    print("\ntrue step accepted / final file check errors")
    for name, rs in runs.items():
        ok = [r for r in rs if "error" not in r]
        acc = sum(s["true_ok"] is True for r in ok for s in r["steps"])
        n = sum(len(r["steps"]) for r in ok)
        errs = [r["final_errors"] for r in ok]
        print(f"  {name:12} true step ok {acc}/{n}; final errors {sum(e or 0 for e in errs)} (unknown: {errs.count(None)})")

for name, rs in runs.items():
    for r in rs:
        if "error" in r:
            print(f"FAILED {name}: {r['task']}: {r['error'][:200]}")

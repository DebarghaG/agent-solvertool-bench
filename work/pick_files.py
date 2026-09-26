"""Seeded sample of large source files per project (>= MIN_LINES), excluding tests/blueprints."""
import json, random, sys
from pathlib import Path

PROJECTS = {"pfr": "PFR", "FLT": "FLT", "carleson": "Carleson", "PrimeNumberTheoremAnd": "PrimeNumberTheoremAnd"}
MIN_LINES, PER_PROJECT = 300, 4
root = Path.home() / "beam-bench/projects"
rng = random.Random(0)
out = []
for proj, lib in PROJECTS.items():
    files = sorted(p for p in (root / proj / lib).rglob("*.lean")
                   if len(p.read_text().splitlines()) >= MIN_LINES and "test" not in p.parts)
    for p in rng.sample(files, PER_PROJECT):
        rel = p.relative_to(root / proj).as_posix()
        out.append({"project": proj, "file": rel, "module": rel[:-5].replace("/", "."),
                    "lines": len(p.read_text().splitlines())})
json.dump(out, sys.stdout, indent=1)

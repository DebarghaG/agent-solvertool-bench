"""Find theorems whose proof is a flat `by` block of top-level tactic steps, using the Lean REPL.

Usage: extract.py files.json OUT.json [PER_FILE]
Each task records the exact source span of every top-level step, so a harness can replace the proof
with `sorry` and replay it step by step. Steps come from REPL `allTactics` spans, not heuristics.
"""
import json, random, re, subprocess, sys
from pathlib import Path

ROOT = Path.home() / "beam-bench/projects"
REPL = Path.home() / "beam-bench/repl"
MIN_STEPS, MAX_STEPS = 3, 12
DECL = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|nonrec)\s+)*(theorem|lemma)\s+(\S+)")


def repl_tactics(project: str, rel: str) -> list[dict]:
    toolchain = (ROOT / project / "lean-toolchain").read_text().strip().split(":")[-1]
    repl = REPL / f"repl-{toolchain}" / ".lake/build/bin/repl"
    cmd = json.dumps({"path": rel, "allTactics": True}) + "\n\n"
    out = subprocess.run(["lake", "env", str(repl)], cwd=ROOT / project, input=cmd,
                         capture_output=True, text=True, timeout=3600)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-2000:])
    data = json.loads(out.stdout)
    errors = [m for m in data.get("messages", []) if m["severity"] == "error"]
    if errors:
        print(f"  {rel}: {len(errors)} elaboration errors; skipping affected theorems", file=sys.stderr)
    return data.get("tactics", []), errors


def tasks_for(project: str, rel: str) -> list[dict]:
    lines = (ROOT / project / rel).read_text().splitlines()
    tactics, errors = repl_tactics(project, rel)
    error_lines = {m["pos"]["line"] for m in errors}
    decls = [(i, m.group(2)) for i, line in enumerate(lines) if (m := DECL.match(line))]
    starts = [i for i, _ in decls] + [len(lines)]
    out = []
    for (start, name), nxt in zip(decls, starts[1:]):
        # the statement must end with `:= by` on some line, and the proof starts on the next line
        by_line = next((j for j in range(start, nxt) if lines[j].rstrip().endswith(":= by")), None)
        if by_line is None or by_line + 1 >= nxt:
            continue
        body = lines[by_line + 1]
        indent = len(body) - len(body.lstrip(" "))
        if indent == 0 or not body.strip():
            continue
        # proof body: following lines until dedent below `indent` (ignoring blanks)
        end = by_line + 1
        while end < nxt and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip(" ")) >= indent):
            end += 1
        while end > by_line + 1 and not lines[end - 1].strip():
            end -= 1
        # REPL lines are 1-based; top-level steps start a line at exactly `indent`
        starts_ = sorted({t["pos"]["line"] - 1 for t in tactics
                          if by_line + 1 <= t["pos"]["line"] - 1 < end and t["pos"]["column"] == indent
                          and lines[t["pos"]["line"] - 1][:indent].strip() == ""})
        if not starts_ or starts_[0] != by_line + 1:
            continue
        # every non-blank line at `indent` must be a step start (no stray `where`, comments, etc.)
        at_indent = [j for j in range(by_line + 1, end)
                     if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip(" ")) == indent]
        if at_indent != starts_ or not MIN_STEPS <= len(starts_) <= MAX_STEPS:
            continue
        if any(by_line <= l - 1 < end for l in error_lines):
            continue
        steps = []
        for a, b in zip(starts_, starts_[1:] + [end]):
            text = "\n".join(l[indent:] if l[:indent].strip() == "" else l for l in lines[a:b]).rstrip()
            steps.append({"line": a, "text": text})
        if any("sorry" in s["text"] or s["text"].lstrip().startswith("--") for s in steps):
            continue
        out.append({"project": project, "file": rel, "theorem": name, "decl_line": start,
                    "by_line": by_line, "indent": indent, "proof_start": by_line + 1, "proof_end": end,
                    "file_lines": len(lines), "steps": steps})
    return out


if __name__ == "__main__":
    files = json.load(open(sys.argv[1]))
    per_file = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    rng = random.Random(0)
    result = []
    for f in files:
        print(f"extract {f['project']}/{f['file']}", file=sys.stderr, flush=True)
        found = tasks_for(f["project"], f["file"])
        chosen = sorted(rng.sample(found, min(per_file, len(found))), key=lambda t: t["decl_line"])
        print(f"  {len(found)} candidate theorems, chose {[t['theorem'] for t in chosen]}", file=sys.stderr)
        result += chosen
    json.dump(result, open(sys.argv[2], "w"), indent=1)

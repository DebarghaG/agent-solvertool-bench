# agent-solvertool-bench

A benchmark of agent-facing Lean proof tools, comparing `lean-beam` and
`lean-lsp-mcp` while replaying proofs from real mathematics projects. It measures
tool latency and candidate-result agreement. Proof steps are supplied from the
original source; no language model or proof-search policy is evaluated.

## Dataset

The checked-in dataset contains **29 proofs, 132 steps, and 396 candidate attempts
per run**, from 15 source files across four projects.

| Project | Subject | Proofs | Steps | Lean version |
| --- | --- | ---: | ---: | --- |
| [PFR](https://github.com/teorth/pfr) | Polynomial Freiman–Ruzsa, entropy, probability | 6 | 22 | v4.35.0-rc2 |
| [Carleson](https://github.com/fpvandoorn/carleson) | Fourier and harmonic analysis | 7 | 28 | v4.34.0-rc2 |
| [PrimeNumberTheoremAnd](https://github.com/AlexKontorovich/PrimeNumberTheoremAnd) | Analytic number theory | 8 | 37 | v4.33.1 |
| [FLT](https://github.com/ImperialCollegeLondon/FLT) | Supporting mathematics for Fermat's Last Theorem | 8 | 45 | v4.35.0-rc2 |

`pick_files.py` samples four files of at least 300 lines per project, using seed 0.
`extract.py` selects up to two eligible proofs per input file, also with seed 0.
Eligible proofs have 3–12 top-level tactic steps and no `sorry` in their extracted
steps. Lean REPL tactic positions identify step boundaries; source indentation
and declaration filters restrict the eligible proof shapes. A step can contain a
multiline subproof. The saved proofs have 3–10 steps, in files of 318–3,683 lines.
The initial selection has 16 files; 15 contribute tasks.

Each task stores its project, file, theorem name, source positions, and exact step
text. Source positions in task JSON are zero-based.

## Experiment

For each task, the harness replaces the proof with `sorry`, preserving the
surrounding file. At each step it tries the original tactic and two alternatives,
`simp` and `linarith`, then continues along the original proof. At the end it
restores the original file and requests a whole-file diagnostic check.

| Mode | Tool calls and state progression |
| --- | --- |
| `beam-handle` | `lean_run_at_handle`, then `lean_run_with` on retained proof states. Falls back to editing if no continuation handle is returned. |
| `beam-edit` | Writes preceding steps, calls `lean_update`, and checks candidates with `lean_run_at`. |
| `lsp` | Writes preceding steps and checks candidates with `lean_multi_attempt`. |

`run.sh` executes these modes sequentially, followed by a second `beam-handle`
run. Each run has a 32 GB systemd memory cap. The harness uses one client per
project and reuses it across that project's tasks. BEAM explicitly uses four
Lean threads; the LSP mode inherits its environment's defaults. Tool calls have
a 900-second timeout.

## Recorded results

These figures summarize the checked-in results, not a fresh run on the reader's
machine. The recorded environment was Linux aarch64 with Python 3.12.3.

| Run | Median step wall time | Sum of step times | Sum of task times |
| --- | ---: | ---: | ---: |
| `beam-handle` | 0.07 s | 14.7 s | 241.0 s |
| `beam-edit` | 0.11 s | 27.4 s | 246.0 s |
| `lsp` | 5.31 s | 1,729.4 s | 2,027.3 s |
| `beam-handle-2` | 0.08 s | 14.8 s | 232.8 s |

Step wall time includes the candidate batch and routine step updates. In handle
mode, fallback edits after a failed continuation are included in task time but
outside step time. Task time includes initial file synchronization and the final
check; server startup and shutdown are excluded.

All four runs completed all 29 tasks, with zero errors reported on the restored
files. BEAM accepted 128/132 original steps; LSP accepted 129/132. Each BEAM run
agreed with LSP on 395/396 candidate results. The disagreement was in
`cntp_approxOnCube_eq`.

The harness advances using the original step even when its isolated check fails.
The final check uses the restored original proof. Therefore task completion and
final-file success do not imply that every intermediate candidate was accepted.
LSP acceptance is based on errors within the candidate's source lines, while
BEAM supplies a `success` flag; this is a comparison of those operational
signals, not proof-state equivalence. This small, filtered sample and fixed run
order do not establish universal performance ratios or cold-start behavior.

## Inspect the saved results

Only Python's standard library is needed:

```bash
python3 work/analyze.py
```

The report includes aggregate timings, per-project step times, timings grouped
by source lines after the theorem, candidate agreement, and final diagnostics.

## Replay and provenance

[provenance.json](provenance.json) records the exact upstream commits, Lean
toolchains, installed BEAM payload, and Python package versions. Project
checkouts, tool installations, virtual environments, and build caches are
excluded from this repository.

The scripts are preserved from the original experiment and expect the checkout
at `$HOME/beam-bench`, with these external dependencies prepared:

- Project repositories at `projects/{pfr,carleson,PrimeNumberTheoremAnd,FLT}`,
  checked out at the recorded commits, with their selected modules and imports
  built. `work/build.sh` provides the original build helper.
- The BEAM MCP executable at `beam/bin/lean-beam-mcp`, installed from the
  recorded BEAM revision. Its installer supports `BEAM_BIN_HOME` and
  `BEAM_INSTALL_ROOT` to select `beam/bin` and `beam/share`.
- The same BEAM source checkout's Python helpers. `work/stitch.py` currently
  imports them from `/home/debargha/lean-beam/scripts`; adjust that path on other
  machines.
- A virtual environment at `venv/` with the packages in `requirements.txt`.
- For regenerating tasks, Lean REPL executables at
  `repl/repl-<version>/.lake/build/bin/repl`. The v4.33.1 checkout used the
  recorded REPL commit with its `lean-toolchain` changed from v4.33.0 to v4.33.1.
- Lean/Lake on `PATH` and a systemd user session for the shell wrappers.

After preparing that environment:

```bash
bash work/run.sh
python3 work/analyze.py
```

The runner temporarily edits project files and restores them in a `finally`
block. Use clean project checkouts. Running the wrapper replaces the saved JSON
results and logs with the new measurements. Full environment setup and a fresh
benchmark run are not automated by this repository.

## Files

- `work/pick_files.py`, `files*.json`: source-file selection.
- `work/extract.py`, `tasks*.json`: task extraction and the saved dataset.
- `work/stitch.py`, `run.sh`, `build.sh`: replay and preparation helpers.
- `work/results/`, `work/logs/`, `work/run.log`: complete recorded runs.
- `work/analyze.py`: result summaries and agreement checks.
- `provenance.json`: source and tool revisions.
- `THIRD_PARTY_NOTICES.md`, `third_party/`: attribution and upstream licenses
  for the extracted proof snippets.

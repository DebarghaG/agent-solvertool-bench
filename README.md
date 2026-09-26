# agent-solvertool-bench

A benchmark of the tools agents use while solving problems. The current
experiment compares `lean-beam` and `lean-lsp-mcp` on proof replay from real Lean
mathematics projects, measuring tool latency and candidate-result agreement.

## Why benchmark the tools?

An agent's performance depends on the tools inside its problem-solving loop.
Each attempt can involve checking a candidate, interpreting feedback, updating
state, and deciding what to try next. The time and behavior of those operations
affect how much useful work an agent can do within a time or compute budget.
We want to measure that part of the system directly: how quickly tools respond,
how they behave across a sequence of interactions, and whether their feedback
agrees on the same attempted steps.

The goal is to evaluate tools on **near-real interaction traces**. Here, those
traces are constructed by replaying existing proofs in their original project
context: try candidates, advance the proof, and check the completed file. The
mathematics, imports, surrounding declarations, and sequence of proof states
come from real projects. Candidate selection is scripted, with the original
step supplied at each point. These are controlled approximations of an agent's
tool-use loop, not recordings of autonomous agent sessions, and they do not
measure a model's ability to discover proofs.

We are building a repeatable way to study this behavior as datasets, tools, and
agent workflows evolve. The checked-in corpus and results are one snapshot.
Larger or different corpora, newer tool versions, and different candidate sets
can become further experiments, with their inputs and environment recorded so
that changes in performance can be investigated. The current implementation
focuses on Lean; additional tool interfaces or trace formats require adapters.

## How the design serves that goal

| Benchmark component | Purpose in evaluating agent tool use |
| --- | --- |
| Real projects and complete source files | Preserve imports, local context, and downstream declarations that can affect the cost of checking a step. |
| Seeded file selection and REPL-based step extraction | Produce inspectable workloads that can be regenerated at pinned source revisions. |
| Several candidates at each proof state | Exercise the feedback an agent receives when exploring alternatives. Alternatives may succeed or fail; they are not labeled as necessarily wrong. |
| Replay along the same original proof | Give each tool the same intended sequence of states without introducing variation from a model's decisions. |
| Handle-based and edit-based modes | Measure the effect of retaining proof state versus advancing through source edits, as well as differences between tools. |
| Opening, step, and final-check timings | Expose both the cost of the repeated interaction loop and the surrounding work an agent must wait for. |
| Candidate outcomes, failures, and final diagnostics | Make behavior visible alongside speed, including cases where an original step fails in isolation. |
| Per-project, tail-latency, and source-position analysis | Show which workloads and contexts account for slow interactions that an aggregate average can hide. |
| Saved task JSON, raw results, and provenance | Support comparisons on the same workload when tools change, and document deliberate changes to the workload itself. |

The [evaluation guide](docs/EVALUATION.md) explains how to adjust the experiment,
add datasets, compare tool versions, and keep results interpretable.

## Dataset

The current checked-in dataset contains **29 proofs, 132 steps, and 396 candidate attempts
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

These are the settings of the recorded experiment. Dataset size, proof length,
candidate lists, resources, and repetitions can be varied as described in
[Adjusting the evaluation](docs/EVALUATION.md#adjustable-parameters).

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

- `docs/EVALUATION.md`: parameter reference, experiment examples, and guidance
  for adding datasets and tool versions.
- `work/pick_files.py`, `files*.json`: source-file selection.
- `work/extract.py`, `tasks*.json`: task extraction and the saved dataset.
- `work/stitch.py`, `run.sh`, `build.sh`: replay and preparation helpers.
- `work/results/`, `work/logs/`, `work/run.log`: complete recorded runs.
- `work/analyze.py`: result summaries and agreement checks.
- `provenance.json`: source and tool revisions.
- `THIRD_PARTY_NOTICES.md`, `third_party/`: attribution and upstream licenses
  for the extracted proof snippets.

# Adapting the evaluation

The benchmark is intended to grow with the tools and workflows agents use.
Each experiment should answer a concrete question: does a new tool version
reduce the time spent checking the same candidates, does a larger candidate
batch change that cost, or does the behavior hold on another mathematical
corpus? Keep the other inputs fixed where possible, and save the inputs and
results together so that the comparison can be revisited.

The current harness replays known proof steps. Its near-real traces preserve
project context and successive proof states, while fixing the route through the
proof. Longer search branches, model-chosen candidates, and traces captured
from live agents are possible extensions; they are not implemented by the
current replay loop.

## Adjustable parameters

Some parameters are command-line arguments; others are constants or choices in
the scripts. There is currently no shared configuration file.

| Parameter | Current setting | How to change it | What it changes |
| --- | --- | --- | --- |
| Task set | `work/tasks.json` | Second argument to `work/stitch.py` | Which proofs and source contexts are replayed. |
| Tool mode | `beam-handle`, `beam-edit`, or `lsp` | First argument to `work/stitch.py` | Tool interface and method of advancing proof state. |
| Alternative candidates | `["simp","linarith"]` | Third argument to `work/stitch.py`, as a JSON list; `DIS` in `work/run.sh` | Breadth and type of candidate checking at each step. |
| Result destination | `work/results/<mode>.json` | Fourth argument to `work/stitch.py` | Where the run's raw results are saved; its parent directory must exist. |
| Source projects | Four entries | `PROJECTS` in `work/pick_files.py` | Project checkout names and source-library directories sampled. |
| Source-file size | At least 300 lines | `MIN_LINES` in `work/pick_files.py` | Amount of surrounding source context represented in the sample. |
| Files per project | 4 | `PER_PROJECT` in `work/pick_files.py` | Corpus breadth; every project needs at least this many eligible files. |
| Sampling seeds | 0 for files and proofs | `random.Random(0)` in both `work/pick_files.py` and `work/extract.py` | Which eligible examples are chosen. Preserve input ordering as well as seeds for reproduction. |
| Proofs per input file | Up to 2 | Optional third argument to `work/extract.py` | Number of eligible proofs sampled from each file. |
| Proof length | 3–12 top-level steps | `MIN_STEPS`, `MAX_STEPS` in `work/extract.py` | Length of the replayed interaction sequences. |
| Tool-call timeout | 900 seconds | `TIMEOUT` in `work/stitch.py` | Maximum wait per tool call. An LSP candidate batch is one call; BEAM candidates use separate calls. |
| Extraction timeout | 3,600 seconds per file | `timeout` in `repl_tactics()` in `work/extract.py` | Time allowed for the REPL to process a source file during dataset preparation. |
| Run memory limit | 32 GB | `MemoryMax=32G` in `work/run.sh`, or the `systemd-run` options used for a direct run | Resource budget for the run; the Python runner alone does not impose this cap. |
| Lean threads | BEAM: 4; LSP: inherited default | BEAM: third argument to `Mcp(...)` in `Beam.__init__`; LSP: inherited `LEAN_NUM_THREADS` | Available Lean execution threads. Setting the environment alone does not override BEAM's explicit value. |
| Run order and repetitions | Handles, edits, LSP, handles again | Loop in `work/run.sh`, or invoke `stitch.py` repeatedly with distinct output files | Repetition and sensitivity to execution order or warm caches. |
| Executables and source roots | Original experiment's paths | `ROOT`, `BEAM`, `LSP`, and the helper import in `work/stitch.py`; root paths in extraction/selection and shell scripts | Which installations and project checkouts are used. |

The runner always prepends the original proof step to the alternative list and
omits alternatives exactly equal to that original text. `[]` checks only the
original step. Three attempts per step is therefore a property of the saved
experiment, not a fixed requirement. Candidate order is preserved, and an
alternative is allowed to succeed without becoming the continuation used for
the next step.

`PAD = 40` in `work/stitch.py` reserves blank lines after `sorry` for LSP's
multiline candidate splice. It is a source-preservation detail, not an intended
performance parameter. If a new dataset has longer multiline candidates,
ensure the padding covers the splice and verify source preservation before
running that workload.

Build preparation has separate resource settings: `work/build.sh` uses an 8 GB
soft memory threshold, a 10 GB hard cap, and up to three attempts. These are
outside the timed replay. Changing a build limit does not change the benchmark
run's memory limit.

## Run a separate experiment

After preparing the environment described in the [README](../README.md#replay-and-provenance),
run these commands from the repository root. This example adds `assumption` to
the alternatives and saves a separate result set:

```bash
bench_trial=work/runs/candidate-set-a
bench_candidates='["simp","linarith","assumption"]'
mkdir -p "$bench_trial/results"
cp work/tasks.json work/analyze.py "$bench_trial/"

for bench_mode in beam-handle beam-edit lsp; do
  bench_python=python3
  if [ "$bench_mode" = lsp ]; then
    bench_python=venv/bin/python
  fi
  LEAN_NUM_THREADS=4 systemd-run --user --scope -q -p MemoryMax=32G \
    "$bench_python" work/stitch.py "$bench_mode" "$bench_trial/tasks.json" \
    "$bench_candidates" "$bench_trial/results/$bench_mode.json"
done

python3 "$bench_trial/analyze.py"
```

The copied analyzer reads `tasks.json` and `results/` beside itself, so this
layout keeps the new experiment independent of the checked-in results. The
analyzer has no command-line option for those paths. Use the mode names above
for result filenames if you want its BEAM-versus-LSP agreement report.

Run repeats with the same mode argument and a new output filename, such as
`beam-handle-2.json`. In the shell wrapper, only the literal `-2` suffix is
stripped before selecting the mode; additional labels need corresponding shell
changes or direct calls to `stitch.py`.

Use the same tasks, candidate texts, and candidate order across the runs within
one comparison. The analyzer aligns attempts by position and assumes compatible
workloads. It is not suitable for directly comparing different candidate lists
or different proof revisions placed in the same results directory.

## Add or expand a dataset

1. Prepare the new Lean project at a recorded commit under `projects/`. Install
   its toolchain and dependencies, and prepare a compatible REPL if extracting
   new tasks. Record any local patches.
2. Add its checkout name and library directory to `PROJECTS` in
   `work/pick_files.py`, or supply a file manifest directly. File manifests have
   `project`, `file`, `module`, and `lines` fields, as shown in
   [`work/files.json`](../work/files.json).
3. Adjust file count, minimum file size, seeds, or proof-length bounds as needed.
   Save a fresh manifest and build the selected modules and their imports before
   extraction. `work/build.sh` reads `work/files.json` specifically; change that
   input path to use it with a different manifest.
4. Extract tasks, passing the desired maximum number of proofs per file. For
   example, after saving and building `work/runs/corpus-b/files.json`:

   ```bash
   python3 work/extract.py work/runs/corpus-b/files.json \
     work/runs/corpus-b/tasks.json 4
   ```

5. Inspect the resulting task count and distribution; files may contribute fewer
   eligible proofs than requested. Copy `work/analyze.py` beside the new
   `tasks.json`, create a sibling `results/`, and replay each mode against that
   task file as in the previous example.

Changing a project revision can move declarations or alter their proofs.
Regenerate tasks after such a change: saved line numbers and step text are tied
to the source revision. Raising the proof-length limit does not expand the
extractor's supported syntax; its declaration and indentation filters still
apply. A different trace source must produce the fields consumed by the replay
harness or introduce a corresponding adapter.

`work/run.sh` rebuilds `work/tasks.json` from the four named `tasks-*.json` files
on every invocation. To include another project in that workflow, update its
merge list. Direct calls with a separate task file avoid that fixed list.

## Compare newer tool versions

Keep the dataset and project revisions fixed when measuring a tool update. This
lets the comparison address the change in the tool on the same sequence of
attempts. Install each version at a recorded revision, update the executable
path or environment used by its client, and save its measurements as a separate
run. For BEAM, keep the imported `beam_pool` helpers compatible with the chosen
MCP executable. For LSP, record both the `lean-lsp-mcp` and MCP client versions.

The adapters in `work/stitch.py` depend on specific tool names and response
fields. If a newer release changes those APIs, update the adapter and check the
meaning of success, diagnostics, and proof-state continuation before comparing
timings. The result schema should continue to record the task identity, phases,
step timings, candidate outcomes, and final diagnostics expected by the
analyzer. Adding another tool currently requires code in client setup and the
replay branches; it is not a plug-in configuration option.

If an update also requires a different Lean toolchain or project revision,
record those changes and regenerate the tasks as needed. Such a run compares a
changed environment as well as a changed tool.

## Record and interpret each experiment

Save the exact task and file manifests, raw results, logs, harness revision and
local changes, project and tool commits, package and Lean versions, machine
details, candidates, seeds, limits, thread settings, and run order. Use
[`provenance.json`](../provenance.json) as a template for a new record, updating
it to describe the actual experiment. The runner does not capture this metadata
automatically. Keep the provenance for the checked-in results associated with
those results.

Evaluate speed together with behavior: completion and failure counts, original
step acceptance, agreement between tools, and final diagnostics. Inspect
per-project results and the slow tail as well as aggregate timings. If some
runs fail tasks, compare timing on common completed tasks and report the
failures; totals over different completed workloads are not like-for-like.

Opening and final checking contribute to task time; startup, shutdown, and
dependency builds do not. Clients are reused within a project, and the current
wrapper does not reset caches or randomize order. Repetitions and alternate
orders can help reveal variation, but a cold-start experiment would require
explicit lifecycle and cache controls. Memory caps constrain the run; the
current harness does not measure peak memory or CPU usage.

Finally, success here describes the tool's feedback on the supplied replay.
LSP's local diagnostic test and BEAM's success flag are distinct operational
signals. Final diagnostics concern the restored original proof. An experiment
with actual agent-generated traces would also need to record the agent's
candidate choices, branches, retries, and stopping conditions to answer broader
questions about the complete agent-and-tool system.

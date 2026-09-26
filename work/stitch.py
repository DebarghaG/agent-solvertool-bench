"""Replay real proofs step by step, the way an agent stitches a proof together.

Usage: stitch.py {beam-handle|beam-edit|lsp} tasks.json DISTRACTORS_JSON OUT.json

For each theorem the proof body is replaced by `sorry` (the rest of the file is untouched). At each
step the agent tries [true step, *distractors] at the current goal, keeps the true step, and moves on.
When all steps are placed, the original file is restored and fully checked, as an agent would do
before moving on.

  beam-handle  step via lean_run_at_handle / lean_run_with on the previous step's handle
  beam-edit    write accepted steps into the file, lean_update, lean_run_at at the new `sorry`
  lsp          write accepted steps into the file, lean_multi_attempt at the new `sorry`
"""
import asyncio, json, os, sys, time
from collections import defaultdict
from pathlib import Path

mode, tasks_file, distractors_json, out = sys.argv[1:5]
tasks = json.load(open(tasks_file))
distractors = json.loads(distractors_json)
ROOT = Path.home() / "beam-bench/projects"
BEAM = Path.home() / "beam-bench/beam/bin/lean-beam-mcp"
LSP = Path.home() / "beam-bench/venv/bin/lean-lsp-mcp"
TIMEOUT = 900
PAD = 40  # blank lines after `sorry`, so lean-lsp-mcp's multi-line splice never eats real source


def stitched(original: list[str], task: dict, placed: list[str]) -> tuple[str, int]:
    """File text with `placed` steps followed by `sorry`; returns (text, 0-based sorry line)."""
    ind = " " * task["indent"]
    body = [ind + l if l.strip() else l for s in placed for l in s.split("\n")]
    sorry_line = task["proof_start"] + len(body)
    lines = original[:task["proof_start"]] + body + [ind + "sorry"] + [""] * PAD + original[task["proof_end"]:]
    return "\n".join(lines) + "\n", sorry_line


def attempts_for(step: str) -> list[str]:
    return [step] + [d for d in distractors if d != step]


class Beam:
    def __init__(self, root: str):
        sys.path.insert(0, "/home/debargha/lean-beam/scripts")
        from beam_pool.mcp import Mcp
        from beam_pool.protocol import Failure
        self.Failure = Failure
        self.mcp = Mcp([str(BEAM)], root, 4)
        self.ws = {"root": root}

    async def start(self):
        await self.mcp.start()

    async def call(self, name, **args):
        return await asyncio.wait_for(self.mcp.call(name, {"workspace": self.ws, **args}), TIMEOUT)

    async def close(self):
        await self.mcp.close()


class Lsp:
    def __init__(self, root: str):
        self.root = root

    async def start(self):
        from contextlib import AsyncExitStack
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self.stack = AsyncExitStack()
        env = dict(os.environ, LEAN_PROJECT_PATH=self.root)
        params = StdioServerParameters(command=str(LSP), args=[], env=env, cwd=self.root)
        r, w = await self.stack.enter_async_context(stdio_client(params, errlog=open(os.devnull, "w")))
        self.session = await self.stack.enter_async_context(ClientSession(r, w))
        await self.session.initialize()

    async def call(self, name, **args):
        res = await asyncio.wait_for(self.session.call_tool(name, args), TIMEOUT)
        if res.is_error:
            raise RuntimeError(str(res.content)[:500])
        return res.structured_content

    async def close(self):
        await self.stack.aclose()


async def run_task(client, task: dict) -> dict:
    path = ROOT / task["project"] / task["file"]
    original_text = path.read_text()
    original = original_text.splitlines()
    rel = task["file"]
    col = task["indent"]
    steps_out = []
    t_task = time.monotonic()
    try:
        text, sorry = stitched(original, task, [])
        path.write_text(text)
        s = time.monotonic()
        if mode == "lsp":
            await client.call("lean_diagnostic_messages", file_path=rel)
            version = None
        else:
            version = (await client.call("lean_sync", path=rel))["version"]
        open_secs = time.monotonic() - s
        handle = None
        placed = []
        for i, step in enumerate(task["steps"]):
            cands = attempts_for(step["text"])
            s = time.monotonic()
            results = []
            if i > 0 and mode != "beam-handle":
                text, sorry = stitched(original, task, placed)
                path.write_text(text)
                if mode == "beam-edit":
                    version = (await client.call("lean_update", path=rel))["version"]
            if mode == "lsp":
                res = await client.call("lean_multi_attempt", file_path=rel, line=sorry + 1, snippets=cands)
                for c, item in zip(cands, res["items"]):
                    span = range(sorry + 1, sorry + 1 + len(c.split("\n")))
                    results.append({"ok": not any(d["severity"] == "error" and d["line"] in span
                                                  for d in item["diagnostics"])})
            else:
                next_handle = None
                for j, c in enumerate(cands):
                    a = time.monotonic()
                    try:
                        if mode == "beam-handle" and handle is not None:
                            r = await client.call("lean_run_with", path=rel, handle=handle, text=c)
                        elif mode == "beam-handle":
                            r = await client.call("lean_run_at_handle", path=rel, version=version,
                                                  line=sorry, character=col, text=c)
                        else:
                            r = await client.call("lean_run_at", path=rel, version=version,
                                                  line=sorry, character=col, text=c)
                        ok = bool(r["success"])
                        h = r.get("next_handle") or r.get("handle")
                        if h is not None:
                            if j == 0:
                                next_handle = h
                            else:
                                await client.call("lean_release", path=rel, handle=h)
                    except client.Failure as e:
                        ok, h = None, None
                        results.append({"ok": None, "error": e.code, "secs": time.monotonic() - a})
                        continue
                    results.append({"ok": ok, "secs": time.monotonic() - a})
                if mode == "beam-handle":
                    if handle is not None:
                        await client.call("lean_release", path=rel, handle=handle)
                    handle = next_handle
            steps_out.append({"step": i, "wall": time.monotonic() - s, "true_ok": results[0]["ok"],
                              "attempts": [dict(r, text=c[:80]) for r, c in zip(results, cands)]})
            placed.append(step["text"])
            if mode == "beam-handle" and handle is None and i + 1 < len(task["steps"]):
                # the true step failed under isolation; fall back to editing so the replay can continue
                text, sorry = stitched(original, task, placed)
                path.write_text(text)
                version = (await client.call("lean_update", path=rel))["version"]
        if handle is not None:
            await client.call("lean_release", path=rel, handle=handle)
        # restore the real proof and check the whole file, as an agent would before moving on
        path.write_text(original_text)
        s = time.monotonic()
        if mode == "lsp":
            diag = await client.call("lean_diagnostic_messages", file_path=rel)
            final_errors = sum(1 for d in (diag.get("items") or []) if d.get("severity") == "error")
        else:
            await client.call("lean_update", path=rel)
            r = await client.call("lean_sync", path=rel)
            final_errors = r["diagnostics"]["counts"]["error"]
        final_secs = time.monotonic() - s
        return {"task": f"{task['project']}/{rel}:{task['theorem']}", "file_lines": task["file_lines"],
                "open": open_secs, "steps": steps_out, "final_check": final_secs, "final_errors": final_errors,
                "total": time.monotonic() - t_task}
    finally:
        path.write_text(original_text)


async def main():
    by_project = defaultdict(list)
    for t in tasks:
        by_project[t["project"]].append(t)
    results = []
    for project, ts in by_project.items():
        root = str(ROOT / project)
        client = Lsp(root) if mode == "lsp" else Beam(root)
        s = time.monotonic()
        await client.start()
        for t in ts:
            try:
                r = await run_task(client, t)
            except Exception as e:  # keep going; record the failure
                r = {"task": f"{t['project']}/{t['file']}:{t['theorem']}", "error": f"{type(e).__name__}: {e}"[:500]}
            results.append(r)
            print(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()
                              if k in ("task", "open", "final_check", "total", "error")}), flush=True)
            json.dump({"mode": mode, "distractors": distractors, "results": results}, open(out, "w"), indent=1)
        if mode != "lsp":
            for f in {t["file"] for t in ts}:
                try:
                    await client.call("lean_close", path=f)
                except Exception:
                    pass
        await client.close()


asyncio.run(main())

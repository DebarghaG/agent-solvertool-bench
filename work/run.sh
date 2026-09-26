#!/bin/bash
# Full benchmark: every mode over every task, one server at a time, each under a memory cap.
cd ~/beam-bench/work
mkdir -p results logs
DIS='["simp","linarith"]'
python3 -c "
import json; t=[]
for p in ('pfr','carleson','pnt','flt'):
    try: t += json.load(open(f'tasks-{p}.json'))
    except FileNotFoundError: pass
json.dump(t, open('tasks.json','w'), indent=1); print(len(t), 'tasks')"
for mode in beam-handle beam-edit lsp beam-handle-2; do
  py=python3; [ $mode = lsp ] && py=~/beam-bench/venv/bin/python
  echo "=== $mode start $(date +%T)"
  systemd-run --user --scope -q -p MemoryMax=32G $py stitch.py ${mode%-2} tasks.json "$DIS" results/$mode.json > logs/$mode.log 2>&1
  echo "=== $mode end $(date +%T) exit=$?"
done

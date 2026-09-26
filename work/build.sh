#!/bin/bash
# Build each project's selected modules (and their imports) under a memory cap.
cd ~/beam-bench/projects
for p in "$@"; do
  mods=$(python3 -c "import json;print(' '.join(f['module'] for f in json.load(open('$HOME/beam-bench/work/files.json')) if f['project']=='$p'))")
  echo "=== $p $(date +%T): $mods"
  for attempt in 1 2 3; do
    (cd $p && systemd-run --user --scope -q -p MemoryHigh=8G -p MemoryMax=10G lake build $mods 2>&1 | tail -4) && break
    echo "retry $attempt"
  done
  echo "=== $p done $(date +%T)"
done

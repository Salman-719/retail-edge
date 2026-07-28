#!/bin/bash
# Phase 0.2 eager baseline run (inside bench-harness pod; /bench is the hostPath).
set -e
cd /workspace
for c in cam1 cam2; do
  echo "=== $c ==="
  python -u /bench/detect_compare.py \
    --backend eager --weights rtdetr-x.pt \
    --clips "/bench/clips/$c" --max-frames 400 \
    --out-timing "/bench/out/${c}_eager_timing.json" \
    --out-dets "/bench/out/${c}_eager_dets.json"
done
echo BOTH_DONE

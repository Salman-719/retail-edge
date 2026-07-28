"""Phase 0.2 accuracy gate: compare two per-frame detection dumps from
detect_compare.py (e.g. eager .pt vs TRT engine).

Per frame: greedy-match boxes by IoU >= 0.5; a match also requires both being
person dets (they already are). Reports:
  * match_rate   = matched_pairs / max(ref_dets, test_dets)  (symmetric-ish: we
    penalise both missed and spurious boxes)
  * mean_score_delta = mean |score_ref - score_test| over matched pairs

GATE (Phase 2/3): match_rate >= 0.98 AND mean_score_delta < 0.02.
Exit code 0 if gate passes, 1 otherwise.

Usage:
  python accuracy_gate.py --ref cam1_eager_dets.json --test cam1_trt_dets.json
"""
import argparse, json, sys
import numpy as np


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def match_frame(ref, test, thr=0.5):
    """Greedy IoU matching. Returns (n_matched, list_of_score_deltas)."""
    used = set()
    matched, deltas = 0, []
    for r in ref:
        best, bj = thr, -1
        for j, t in enumerate(test):
            if j in used:
                continue
            v = iou(r, t)
            if v >= best:
                best, bj = v, j
        if bj >= 0:
            used.add(bj)
            matched += 1
            deltas.append(abs(r[4] - test[bj][4]))
    return matched, deltas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--min-match-rate", type=float, default=0.98)
    ap.add_argument("--max-score-delta", type=float, default=0.02)
    args = ap.parse_args()

    ref = json.load(open(args.ref))
    test = json.load(open(args.test))
    rf, tf = ref["frames"], test["frames"]
    if rf != tf:
        print("FRAME MISMATCH: ref has %d, test has %d (or different order)" % (len(rf), len(tf)))
        sys.exit(2)

    tot_matched, tot_boxes, all_deltas = 0, 0, []
    for rd, td in zip(ref["detections"], test["detections"]):
        m, d = match_frame(rd, td, args.iou)
        tot_matched += m
        tot_boxes += max(len(rd), len(td))
        all_deltas += d

    match_rate = tot_matched / tot_boxes if tot_boxes else 1.0
    mean_delta = float(np.mean(all_deltas)) if all_deltas else 0.0
    ref_total = sum(len(d) for d in ref["detections"])
    test_total = sum(len(d) for d in test["detections"])

    print("frames=%d | ref_dets=%d test_dets=%d matched=%d" % (len(rf), ref_total, test_total, tot_matched))
    print("match_rate=%.4f (gate >= %.2f)" % (match_rate, args.min_match_rate))
    print("mean_score_delta=%.4f (gate < %.2f)" % (mean_delta, args.max_score_delta))
    ok = match_rate >= args.min_match_rate and mean_delta < args.max_score_delta
    print("GATE", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

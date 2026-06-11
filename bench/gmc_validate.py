"""Phase 4.1 validation: BoTSORT with GMC (camera-motion compensation) on vs off.

Drives BoTSORT with the fixture frames + the eager detection dump, measuring
per-frame tracker update time and track quality (unique tracks, avg tracks/frame,
track-length distribution, a crude ID-switch proxy) for each CMC setting.

Static cameras (D5) => GMC should be near-identical quality at a fraction of the
CPU. This script also empirically finds which boxmot value disables CMC.

Usage (inside a pod with boxmot, e.g. the iep2 image):
  python gmc_validate.py /bench/clips/cam1 /bench/out/cam1_eager_dets.json
"""
import glob, json, os, sys, time
from pathlib import Path
import numpy as np
import cv2
import torch
from boxmot import BoTSORT


def make(cmc):
    return BoTSORT(
        model_weights=Path(""), device=torch.device("cpu"), fp16=False,
        track_buffer=15, match_thresh=0.8, new_track_thresh=0.7,
        track_high_thresh=0.6, with_reid=False, cmc_method=cmc, frame_rate=5,
    )


def run(cmc, label, frames, dets, N):
    t = make(cmc)  # may raise if cmc value invalid
    lengths, per_frame_ms, tracks_per_frame = {}, [], []
    for i in range(N):
        d = dets[i]
        if d:
            arr = np.array([[b[0], b[1], b[2], b[3], b[4], 0.0] for b in d], dtype=float)
        else:
            arr = np.empty((0, 6), dtype=float)
        t0 = time.perf_counter()
        out = t.update(arr, frames[i])
        per_frame_ms.append((time.perf_counter() - t0) * 1000.0)
        tracks_per_frame.append(len(out))
        for row in out:
            tid = int(row[4])
            lengths[tid] = lengths.get(tid, 0) + 1
    a = np.array(per_frame_ms)
    lv = sorted(lengths.values())
    print("RESULT %-14s tracker: mean=%.2f p50=%.2f p95=%.2f ms/frame | "
          "unique=%d avg_tracks/frame=%.2f len_p50=%d len_p95=%d"
          % (label, a.mean(), np.percentile(a, 50), np.percentile(a, 95),
             len(lengths), float(np.mean(tracks_per_frame)),
             int(np.percentile(lv, 50)) if lv else 0,
             int(np.percentile(lv, 95)) if lv else 0), flush=True)
    return {"label": label, "mean_ms": float(a.mean()), "unique": len(lengths),
            "avg_tracks": float(np.mean(tracks_per_frame)), "len_hist": lv}


def main():
    clip, dets_json = sys.argv[1], sys.argv[2]
    frames = [cv2.imread(p) for p in sorted(glob.glob(os.path.join(clip, "*.jpg")))]
    dets = json.load(open(dets_json))["detections"]
    N = min(len(frames), len(dets))
    print("frames=%d dets=%d using N=%d" % (len(frames), len(dets), N), flush=True)

    results = {}
    # GMC ON baseline
    results["on"] = run("sof", "GMC-on(sof)", frames, dets, N)
    # find a working GMC-OFF value
    for cand in [None, "none", "None", ""]:
        try:
            results["off"] = run(cand, "GMC-off(%r)" % cand, frames, dets, N)
            print("DISABLE_VALUE %r works" % cand, flush=True)
            break
        except Exception as e:
            print("disable %r -> %r" % (cand, e), flush=True)

    if "off" in results:
        on, off = results["on"], results["off"]
        speedup = on["mean_ms"] / off["mean_ms"] if off["mean_ms"] else 0
        dtrack = abs(on["unique"] - off["unique"]) / max(1, on["unique"])
        print("SUMMARY tracker speedup x%.1f | unique-track delta %.1f%% (on=%d off=%d)"
              % (speedup, dtrack * 100, on["unique"], off["unique"]), flush=True)
    json.dump(results, open("/bench/out/gmc_validate_%s.json" % os.path.basename(clip), "w"), indent=2)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()

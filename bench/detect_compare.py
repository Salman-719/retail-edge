"""Phase 0.2 detector benchmark + detection-dump harness.

Runs a detector backend over a fixture clip and produces:
  * a latency sweep over batch sizes {1,4,8,16,32}: p50/p95/mean ms-per-frame,
    measured with torch.cuda.synchronize() around each call (end-to-end predict).
    NOTE: we deliberately time the *full* predict (pre + GPU + post), not GPU-only
    CUDA events -- the eager path's cost is CPU-side pre/post, and capturing that
    is the entire point of this comparison (GPU-event timing would undercount it).
  * a per-frame person-detection dump (xyxy + score) to JSON, consumed by
    accuracy_gate.py to prove a TRT engine matches the eager baseline.

Backends (same .infer(list_of_bgr_frames) -> list_of_dets interface):
  eager : ultralytics RTDETR(<.pt>)  -- current production path
  trt   : ultralytics RTDETR(<.engine>) -- Phase 2+ TRT FP16 engine

Usage:
  python detect_compare.py --backend eager --weights rtdetr-x.pt \
      --clips /bench/clips/cam1 --max-frames 400 \
      --out-timing /bench/out/cam1_eager_timing.json \
      --out-dets   /bench/out/cam1_eager_dets.json
"""
import argparse, glob, json, os, time
import numpy as np


def load_frames(clip_dir, max_frames):
    import cv2
    paths = sorted(glob.glob(os.path.join(clip_dir, "*.jpg")))[:max_frames]
    frames = [cv2.imread(p) for p in paths]
    bad = [p for p, f in zip(paths, frames) if f is None]
    if bad:
        raise SystemExit("unreadable frames: %s" % bad[:3])
    return [os.path.basename(p) for p in paths], frames


class UltralyticsBackend:
    """Works for both .pt (eager) and .engine (TRT) -- ultralytics picks the
    backend from the file extension; the .infer interface is identical."""
    def __init__(self, weights, conf):
        from ultralytics import RTDETR
        self.model = RTDETR(weights)
        self.conf = conf

    def infer(self, batch):
        res = self.model.predict(batch, imgsz=640, conf=self.conf, classes=[0],
                                 half=True, verbose=False, device=0)
        out = []
        for r in res:
            dets = []
            b = r.boxes
            if b is not None and len(b):
                xyxy = b.xyxy.cpu().numpy()
                sc = b.conf.cpu().numpy()
                for k in range(len(b)):
                    x = xyxy[k]
                    dets.append([float(x[0]), float(x[1]), float(x[2]), float(x[3]), float(sc[k])])
            out.append(dets)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["eager", "trt"], required=True)
    ap.add_argument("--weights", required=True, help=".pt for eager, .engine for trt")
    ap.add_argument("--clips", required=True)
    ap.add_argument("--max-frames", type=int, default=400)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--batch-sizes", default="1,4,8,16,32")
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--out-timing", required=True)
    ap.add_argument("--out-dets", required=True)
    args = ap.parse_args()

    import torch
    names, frames = load_frames(args.clips, args.max_frames)
    print("loaded %d frames from %s | GPU %s" % (len(frames), args.clips, torch.cuda.get_device_name(0)), flush=True)
    be = UltralyticsBackend(args.weights, args.conf)
    batch_sizes = [int(b) for b in args.batch_sizes.split(",")]

    # warmup (bs=1)
    for i in range(min(args.warmup, len(frames))):
        be.infer([frames[i % len(frames)]])
    torch.cuda.synchronize()

    # detection dump (bs=1, deterministic reference)
    dets_all = [be.infer([f])[0] for f in frames]
    ndet = sum(len(d) for d in dets_all)
    print("detection dump: %d frames, %.2f person/frame avg" % (len(dets_all), ndet / max(1, len(dets_all))), flush=True)

    # timing sweep
    timing = {}
    for bs in batch_sizes:
        per_frame_ms = []
        for s in range(0, len(frames) - bs + 1, bs):
            batch = frames[s:s + bs]
            torch.cuda.synchronize(); t0 = time.perf_counter()
            be.infer(batch)
            torch.cuda.synchronize()
            per_frame_ms.append((time.perf_counter() - t0) / bs * 1000.0)
        a = np.array(per_frame_ms)
        timing[bs] = {"mean_ms": float(a.mean()), "p50_ms": float(np.percentile(a, 50)),
                      "p95_ms": float(np.percentile(a, 95)), "fps": float(1000.0 / a.mean()), "n_calls": len(a)}
        print("RESULT bs=%2d : mean=%.2f p50=%.2f p95=%.2f ms/frame | %.0f fps"
              % (bs, a.mean(), np.percentile(a, 50), np.percentile(a, 95), 1000.0 / a.mean()), flush=True)

    os.makedirs(os.path.dirname(args.out_timing), exist_ok=True)
    json.dump({"backend": args.backend, "weights": args.weights, "clips": args.clips,
               "conf": args.conf, "n_frames": len(frames), "timing": timing},
              open(args.out_timing, "w"), indent=2)
    json.dump({"backend": args.backend, "weights": args.weights, "conf": args.conf,
               "frames": names, "detections": dets_all},
              open(args.out_dets, "w"))
    print("WROTE", args.out_timing, args.out_dets, flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()

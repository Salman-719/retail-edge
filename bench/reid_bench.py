"""Phase 4 ReID decomposition: where does manager.process_frame's ReID time go?

Uses REAL person crops cut from the fixture frames via the eager detection dump,
then measures, separately:
  * per-crop JPEG encode  (client side, iep2)
  * per-crop JPEG decode + resize + normalize  (service side preprocess)
  * resnet50_msmt17 model.forward latency at batch {1,8,16,32,64}, FP32 vs FP16

This isolates model cost (cheap, fix by batching/FP16) from per-crop CPU overhead
(fix by killing the JPEG round-trip).

Run in the reid image:  python reid_bench.py /bench/clips/cam1 /bench/out/cam1_eager_dets.json
"""
import glob, json, sys, time
from pathlib import Path
import numpy as np
import cv2
import torch
from boxmot.appearance.reid_auto_backend import ReidAutoBackend

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess(jpeg_bytes):
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    crop = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if crop is None:
        crop = np.zeros((256, 128, 3), dtype=np.uint8)
    crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    crop = cv2.resize(crop, (128, 256))
    crop = crop.astype(np.float32) / 255.0
    crop = (crop - MEAN) / STD
    return crop.transpose(2, 0, 1)


def main():
    clip, dets_json = sys.argv[1], sys.argv[2]
    frames = [cv2.imread(p) for p in sorted(glob.glob(clip + "/*.jpg"))]
    dets = json.load(open(dets_json))["detections"]
    N = min(len(frames), len(dets))

    crops = []
    for i in range(N):
        f = frames[i]
        h, w = f.shape[:2]
        for b in dets[i]:
            x1, y1, x2, y2 = int(b[0]), int(b[1]), int(b[2]), int(b[3])
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 > x1 and y2 > y1:
                crops.append(f[y1:y2, x1:x2])
    print("collected %d real crops (~%.1f/frame over %d frames)" % (len(crops), len(crops) / N, N), flush=True)

    # per-crop JPEG encode
    t = time.perf_counter()
    jpegs = [cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes() for c in crops]
    enc_ms = (time.perf_counter() - t) / len(crops) * 1000

    # per-crop decode + preprocess
    t = time.perf_counter()
    pres = [preprocess(j) for j in jpegs]
    pre_ms = (time.perf_counter() - t) / len(jpegs) * 1000
    print("RESULT per-crop overhead: jpeg_encode=%.3f ms | decode+preprocess=%.3f ms (sum=%.3f ms/crop)"
          % (enc_ms, pre_ms, enc_ms + pre_ms), flush=True)

    # model forward sweep, FP32 vs FP16
    for half in (False, True):
        rab = ReidAutoBackend(weights=Path("resnet50_msmt17.pt"), device="0", half=half)
        model = rab.model
        dtype = torch.float16 if half else torch.float32
        pool = np.stack(pres[:64])
        for bs in (1, 8, 16, 32, 64):
            batch = torch.tensor(pool[:bs], dtype=dtype, device="cuda")
            for _ in range(5):
                model.forward(batch)
            torch.cuda.synchronize(); t = time.perf_counter(); M = 30
            for _ in range(M):
                model.forward(batch)
            torch.cuda.synchronize(); dt = time.perf_counter() - t
            print("RESULT reid fp16=%-5s bs=%2d : %.2f ms/batch | %.3f ms/crop | %.0f crops/s"
                  % (half, bs, dt / M * 1000, dt / M / bs * 1000, M * bs / dt), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()

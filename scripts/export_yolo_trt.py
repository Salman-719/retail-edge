"""Export YOLOv8 weights to a TensorRT FP16 engine.

Called at Docker image build time via:
    RUN python scripts/export_yolo_trt.py

The exported engine file (yolov8{variant}.engine) is embedded in the image
and loaded at runtime — raw .pt inference is banned (R1).

Environment variables:
    MODEL_VARIANT  — n | s | m  (default: n)
    BATCH_SIZE     — TRT max batch (default: 32, must match YOLO_MAX_BATCH_SIZE)
    IMG_SIZE       — inference image size in pixels (default: 640)
    WORKSPACE_GB   — TRT builder workspace in GB (default: 4)
"""
import os
import sys

MODEL_VARIANT = os.environ.get("MODEL_VARIANT", "n")
BATCH_SIZE    = int(os.environ.get("BATCH_SIZE",    "32"))
IMG_SIZE      = int(os.environ.get("IMG_SIZE",      "640"))
WORKSPACE_GB  = int(os.environ.get("WORKSPACE_GB",  "4"))

VALID_VARIANTS = ("n", "s", "m")
if MODEL_VARIANT not in VALID_VARIANTS:
    print(f"ERROR: MODEL_VARIANT must be one of {VALID_VARIANTS}, got {MODEL_VARIANT!r}",
          file=sys.stderr)
    sys.exit(1)

pt_path     = f"yolov8{MODEL_VARIANT}.pt"
engine_path = f"yolov8{MODEL_VARIANT}.engine"

print(f"Exporting {pt_path} → {engine_path}  "
      f"batch={BATCH_SIZE}  imgsz={IMG_SIZE}  workspace={WORKSPACE_GB}GB  FP16=True")

from ultralytics import YOLO  # noqa: E402

model = YOLO(pt_path)
model.export(
    format="engine",
    half=True,
    device=0,
    batch=BATCH_SIZE,
    imgsz=IMG_SIZE,
    workspace=WORKSPACE_GB,
)
print(f"Export complete: {engine_path}")

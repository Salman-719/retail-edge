"""Export resnet50_msmt17 ReID weights to ONNX, then convert to TensorRT FP16 engine.

Step 1 (this script): boxmot resnet50_msmt17 PyTorch → ONNX with dynamic batch axis.
Step 2 (Dockerfile RUN):
    trtexec --onnx=resnet50_msmt17.onnx --saveEngine=resnet50_msmt17.engine \
            --fp16 \
            --minShapes=input:1x3x256x128 \
            --optShapes=input:64x3x256x128 \
            --maxShapes=input:128x3x256x128

Input tensor: [B, 3, 256, 128] float16 (CHW, ImageNet-normalised).
Output tensor: [B, 2048] float32 embedding (L2 normalisation applied by service at runtime).
"""
import sys
from pathlib import Path

import torch
from boxmot.appearance.reid_auto_backend import ReidAutoBackend

ONNX_PATH  = "resnet50_msmt17.onnx"
WEIGHTS    = Path("resnet50_msmt17.pt")
OPT_BATCH  = int(sys.argv[1]) if len(sys.argv) > 1 else 64
MAX_BATCH  = OPT_BATCH * 2

print(f"Exporting resnet50_msmt17  opt_batch={OPT_BATCH}  max_batch={MAX_BATCH}")

# ReidAutoBackend loads the resnet50_msmt17 backbone and its pretrained weights.
rab = ReidAutoBackend(weights=WEIGHTS, device=torch.device("cuda"), half=True)
model = rab.model.model            # the underlying nn.Module
model.eval().cuda().half()

# Dummy input: [opt_batch, 3, H=256, W=128] — canonical person-ReID input size.
dummy = torch.zeros(OPT_BATCH, 3, 256, 128, dtype=torch.float16, device="cuda")

torch.onnx.export(
    model,
    dummy,
    ONNX_PATH,
    input_names=["input"],
    output_names=["embedding"],
    dynamic_axes={"input": {0: "batch_size"}, "embedding": {0: "batch_size"}},
    opset_version=17,
)
print(f"ONNX export complete: {ONNX_PATH}")
print(
    "Next: run trtexec to generate .engine — see Dockerfile for the full command."
)

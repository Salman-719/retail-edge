"""Export OSNet x1.0 weights to ONNX, then convert to TensorRT FP16 engine.

Step 1 (this script): PyTorch → ONNX with dynamic batch axis.
Step 2 (Dockerfile RUN):
    trtexec --onnx=osnet_x1_0.onnx --saveEngine=osnet_x1_0.engine \
            --fp16 \
            --minShapes=input:1x3x256x128 \
            --optShapes=input:64x3x256x128 \
            --maxShapes=input:128x3x256x128

Input tensor: [B, 3, 256, 128] float16 (CHW, ImageNet-normalised).
Output tensor: [B, 512] float32 embedding (L2 normalisation applied by service at runtime).
"""
import sys

import numpy as np
import torch
import torchreid

ONNX_PATH  = "osnet_x1_0.onnx"
OPT_BATCH  = int(sys.argv[1]) if len(sys.argv) > 1 else 64
MAX_BATCH  = OPT_BATCH * 2

print(f"Exporting OSNet x1.0  opt_batch={OPT_BATCH}  max_batch={MAX_BATCH}")

model = torchreid.models.build_model(
    name="osnet_x1_0",
    num_classes=1,
    pretrained=True,
)
model.eval().cuda().half()

# Dummy input: [opt_batch, 3, H=256, W=128] — OSNet canonical input size.
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

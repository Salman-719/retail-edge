# Jetson JetPack 6.0 base — CUDA, cuDNN, TensorRT 8.6, PyTorch 2.2 (nv24.02).
# ARM64/Jetson-only — will NOT build on x86 or in CI. Build ON a Jetson.
# For x86 dev, use Dockerfile.dev (CPU, no TRT).
#
# IMPORTANT: build from the REPO ROOT so scripts/ and services/ are in context:
#   docker build -f services/reid_service/Dockerfile -t ghcr.io/<owner>/retailvision/reid:1.0.0 .
# The TRT engine build needs the GPU at build time, so the Jetson's Docker
# default runtime must be nvidia (see deployment guide, "GPU edge images").
FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3

WORKDIR /workspace

COPY services/reid_service/requirements.txt services/reid_service/requirements.txt
RUN pip install --no-cache-dir -r services/reid_service/requirements.txt

COPY services/__init__.py services/__init__.py
COPY services/reid_service/ services/reid_service/
COPY scripts/export_reid_trt.py scripts/export_reid_trt.py

# Pre-download resnet50_msmt17 weights (gdown handles Drive's large-file redirect).
RUN gdown --fuzzy "https://drive.google.com/uc?id=1ep7RypVDOthCRIAqDnn4_N-UhkkFHJsj" -O resnet50_msmt17.pt

# Step 1 — export resnet50_msmt17 weights to ONNX at build time.
RUN python scripts/export_reid_trt.py

# Step 2 — ONNX -> TensorRT FP16 engine (dynamic batch). trtexec ships with
# JetPack TensorRT; use the full path since it isn't always on PATH.
RUN /usr/src/tensorrt/bin/trtexec \
    --onnx=resnet50_msmt17.onnx \
    --saveEngine=resnet50_msmt17.engine \
    --fp16 \
    --minShapes=input:1x3x256x128 \
    --optShapes=input:64x3x256x128 \
    --maxShapes=input:128x3x256x128

CMD ["python", "-m", "services.reid_service.service"]

# Jetson JetPack 6.0 base — CUDA, cuDNN, TensorRT 8.6, PyTorch 2.2 (nv24.02).
# ARM64/Jetson-only — will NOT build on x86 or in CI. Build ON a Jetson.
# For x86 dev, use Dockerfile.dev (CPU, no TRT).
#
# IMPORTANT: build from the REPO ROOT so scripts/ and services/ are in context:
#   docker build -f services/osnet_service/Dockerfile -t ghcr.io/<owner>/retailvision/osnet:1.0.0 .
# The TRT engine build needs the GPU at build time, so the Jetson's Docker
# default runtime must be nvidia (see deployment guide, "GPU edge images").
FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3

WORKDIR /workspace

COPY services/osnet_service/requirements.txt services/osnet_service/requirements.txt
RUN pip install --no-cache-dir -r services/osnet_service/requirements.txt

COPY services/__init__.py services/__init__.py
COPY services/osnet_service/ services/osnet_service/
COPY scripts/export_osnet_trt.py scripts/export_osnet_trt.py

# Step 1 — export OSNet weights to ONNX at build time.
RUN python scripts/export_osnet_trt.py

# Step 2 — ONNX -> TensorRT FP16 engine (dynamic batch). trtexec ships with
# JetPack TensorRT; use the full path since it isn't always on PATH.
RUN /usr/src/tensorrt/bin/trtexec \
    --onnx=osnet_x1_0.onnx \
    --saveEngine=osnet_x1_0.engine \
    --fp16 \
    --minShapes=input:1x3x256x128 \
    --optShapes=input:64x3x256x128 \
    --maxShapes=input:128x3x256x128

CMD ["python", "-m", "services.osnet_service.service"]

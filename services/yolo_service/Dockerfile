# Jetson JetPack 6.0 base — provides CUDA, cuDNN, TensorRT 8.6, PyTorch 2.2 (nv24.02).
# ARM64/Jetson-only — will NOT build on x86 or in CI. Build ON a Jetson.
# For x86 dev testing, use Dockerfile.dev (CPU-only, no TRT).
#
# IMPORTANT: build from the REPO ROOT so scripts/ and services/ are in context:
#   docker build -f services/yolo_service/Dockerfile -t ghcr.io/<owner>/retailvision/yolo:1.0.0 .
# The TRT engine export below needs the GPU at build time, so the Jetson's Docker
# default runtime must be nvidia (see deployment guide, "GPU edge images").
FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3

WORKDIR /workspace

# Install Python deps first (layer cached on requirements change).
COPY services/yolo_service/requirements.txt services/yolo_service/requirements.txt
RUN pip install --no-cache-dir -r services/yolo_service/requirements.txt

# Service source (as an importable package) + the export script.
COPY services/__init__.py services/__init__.py
COPY services/yolo_service/ services/yolo_service/
COPY scripts/export_yolo_trt.py scripts/export_yolo_trt.py

# Build-time model variant (n=nano / s=small / m=medium).
ARG MODEL_VARIANT=n
ENV MODEL_VARIANT=${MODEL_VARIANT}

# Export YOLOv8 weights to a TensorRT FP16 engine at build time (R1).
# Needs internet (downloads weights) and the GPU (TRT build).
RUN python scripts/export_yolo_trt.py

CMD ["python", "-m", "services.yolo_service.service"]

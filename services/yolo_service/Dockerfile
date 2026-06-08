# Jetson JetPack 6.0 base — provides CUDA, cuDNN, TensorRT 8.6, PyTorch 2.2 (nv24.02).
# This image is ARM64/Jetson-only and will not build on x86.
# For x86 dev testing, use Dockerfile.dev (CPU-only, no TRT).
FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3

WORKDIR /workspace

# Install Python deps before copying source so layer is cached on requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source and export script.
COPY . services/yolo_service/
COPY ../../scripts/export_yolo_trt.py scripts/export_yolo_trt.py

# Build-time model variant (n=nano / s=small / m=medium).
# Selectable per store tier without code change.
ARG MODEL_VARIANT=n
ENV MODEL_VARIANT=${MODEL_VARIANT}

# Export YOLOv8 weights to TensorRT FP16 engine at build time (R1).
# Engine is baked into the image — no internet access needed at runtime.
RUN python scripts/export_yolo_trt.py

CMD ["python", "-m", "services.yolo_service.service"]

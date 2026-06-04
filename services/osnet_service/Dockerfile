# Jetson JetPack 6.0 base — CUDA, cuDNN, TensorRT 8.6, PyTorch 2.2 (nv24.02).
# ARM64/Jetson only. For x86 dev, use Dockerfile.dev (CPU, no TRT).
FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . services/osnet_service/
COPY ../../scripts/export_osnet_trt.py scripts/export_osnet_trt.py

# Step 1 — export OSNet weights to ONNX at build time.
RUN python scripts/export_osnet_trt.py

# Step 2 — convert ONNX to TensorRT FP16 engine with dynamic batch axis.
# trtexec is part of the JetPack TensorRT installation.
RUN trtexec \
    --onnx=osnet_x1_0.onnx \
    --saveEngine=osnet_x1_0.engine \
    --fp16 \
    --minShapes=input:1x3x256x128 \
    --optShapes=input:64x3x256x128 \
    --maxShapes=input:128x3x256x128

CMD ["python", "-m", "services.osnet_service.service"]

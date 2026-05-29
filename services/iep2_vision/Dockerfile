# IEP2 Vision image.
#
# IMPORTANT: build with the REPO ROOT as context (the service is an importable
# package alongside common/):
#   docker build -f services/iep2_vision/Dockerfile -t iep2-vision .
# The runtime entrypoint (CLI worker, one process per camera) is wired in M4;
# until then this image is for dependency/import smoke-testing only.

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ffmpeg git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU torch (GPU image overrides this layer).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY services/iep2_vision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/iep2_vision /app/services/iep2_vision

# CMD wired in M4 (per-camera CLI worker): python -m services.iep2_vision.app.main ...

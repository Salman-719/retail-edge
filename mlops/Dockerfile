# Eval-runner image (offline MLflow experiments). Python 3.11 to match the
# production services. Containers the MLflow *client* only.
#
# CPU by default. For GPU, pass TORCH_INDEX_URL (mirrors docker-compose.gpu.yml's
# pattern for yolo/reid): the CUDA torch wheel is installed FIRST so it satisfies
# ultralytics' torch dependency (otherwise pip would pull the CPU wheel).
#   build arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121  -> CUDA build
FROM python:3.11-slim

ARG TORCH_INDEX_URL=""

# ca-certificates FIRST: stale/missing CA certs cause the intermittent
# "SSL UNEXPECTED_EOF" failures when pip talks to PyPI. The IEP Dockerfiles
# install this and build cleanly — match that. Plus OpenCV runtime libs (cv2).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libgl1 libglib2.0-0 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install eval deps. setuptools<81 keeps pkg_resources (boxmot imports it); wheel
# lets filterpy (source-only boxmot dep) build. Long timeout + retries ride out
# the occasional SSL drop. With ca-certificates installed above, this mirrors the
# IEP Dockerfiles that already build torch/boxmot/cv2 cleanly.
COPY mlops/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --timeout 300 --retries 20 "setuptools<81" wheel && \
    if [ -n "$TORCH_INDEX_URL" ]; then \
        echo "Installing CUDA torch from $TORCH_INDEX_URL" && \
        pip install --no-cache-dir --timeout 600 --retries 20 \
            --index-url "$TORCH_INDEX_URL" torch torchvision ; \
    fi && \
    pip install --no-cache-dir --timeout 300 --retries 20 -r /tmp/requirements.txt

# Cache ultralytics model weights here; mount a volume to persist across runs.
ENV YOLO_CONFIG_DIR=/workspace/.ultralytics
ENV MLFLOW_TRACKING_URI=http://mlflow:5000
ENV PYTHONPATH=/workspace

# Code + clips are bind-mounted at run time (see docker-compose.dev.yml), so no COPY
# of the source is needed — edits on the host take effect without rebuilding.
CMD ["python", "mlops/eval/run_detection_eval.py", "--smoke"]

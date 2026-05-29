# Orchestrator / demo job image.
#
# Carries everything the EEP stand-in needs to run the full IEP2->IEP3 chain in
# one process: the shared common/ package, BOTH service packages, and tools/.
# Build with the REPO ROOT as context:
#   docker build -f tools/Dockerfile -t rv-orchestrator .
# Invoke as a one-off job (see docker-compose `orchestrator` service):
#   docker compose run --rm orchestrator python -m tools.orchestrator --store-id ... --camera cam1=...

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ffmpeg git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU torch (GPU image overrides this layer). The vision requirements cover the
# DB/reconciliation deps too, so they are a superset for both services.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY services/iep2_vision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/iep2_vision /app/services/iep2_vision
COPY services/iep3_reconciliation /app/services/iep3_reconciliation
COPY tools /app/tools

CMD ["python", "-c", "import tools.orchestrator; print('orchestrator image ready')"]

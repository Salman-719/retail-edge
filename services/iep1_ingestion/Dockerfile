# IEP1 ingestion image.
#
# Build with the REPO ROOT as context (importable package alongside common/):
#   docker build -f services/iep1_ingestion/Dockerfile -t iep1-ingestion .
# Per-camera CLI worker (one process per camera); launched by the orchestrator/EEP.

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY services/iep1_ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/iep1_ingestion /app/services/iep1_ingestion

# CLI worker (per camera): one process per camera, launched by the orchestrator.
# CMD ["python", "-m", "services.iep1_ingestion.app.main", "--store-id", "...", ...]

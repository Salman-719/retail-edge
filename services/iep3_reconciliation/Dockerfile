# IEP3 cross-camera reconciliation image.
#
# Build with the REPO ROOT as context (importable package alongside common/):
#   docker build -f services/iep3_reconciliation/Dockerfile -t iep3-reconciliation .
# No vision/GPU dependencies -- pure data processing.

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

COPY services/iep3_reconciliation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY services/iep3_reconciliation /app/services/iep3_reconciliation

# Single-instance coordinator. cameras/frame_px come from store config (M6 wiring):
# CMD ["python", "-m", "services.iep3_reconciliation.app.main", "--store-id", "...", "--cameras", "..."]

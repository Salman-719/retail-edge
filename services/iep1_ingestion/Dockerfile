FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Mirror module path: services.iep1_ingestion.app.*
RUN mkdir -p services/iep1_ingestion
COPY app/ services/iep1_ingestion/app/
RUN touch services/__init__.py services/iep1_ingestion/__init__.py services/iep1_ingestion/app/__init__.py

# IEP1 daemon: receives AddCamera/RemoveCamera via gRPC control socket.
# Cameras are NOT passed as CLI args — Edge Agent calls AddCamera at runtime.
CMD ["python", "-m", "services.iep1_ingestion.app.main"]

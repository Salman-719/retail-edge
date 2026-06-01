FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Mirror module path: services.iep1_ingestion.app.*
RUN mkdir -p services/iep1_ingestion
COPY app/ services/iep1_ingestion/app/
RUN touch services/__init__.py services/iep1_ingestion/__init__.py

# Default to --help; docker-compose overrides with real args via env vars.
CMD ["python", "-m", "services.iep1_ingestion.app.main", "--help"]

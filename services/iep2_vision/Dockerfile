FROM python:3.11-slim

WORKDIR /workspace
RUN apt-get update && apt-get install -y ca-certificates
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build the services.iep2_vision package tree inside the container.
# The docker-compose build context is the iep2_vision/ directory itself,
# so we nest it under services/iep2_vision/ to match the module path.
RUN mkdir -p services/iep2_vision
COPY . services/iep2_vision/

# Top-level services package marker (not in the build context).
RUN touch services/__init__.py

# Pre-download ReID (OSNet) weights from Google Drive at build time so the
# container never needs outbound internet access to Google Drive at runtime.
RUN python -c "from services.iep2_vision.reid.reid import load_model; load_model(); print('ReID weights cached.')"

EXPOSE 8002

CMD ["python", "-m", "uvicorn", "services.iep2_vision.app.main:app", "--host", "0.0.0.0", "--port", "8002"]

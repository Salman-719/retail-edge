FROM python:3.11-slim

WORKDIR /workspace
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Build the services.iep2_vision package tree inside the container.
# The docker-compose build context is the iep2_vision/ directory itself,
# so we nest it under services/iep2_vision/ to match the module path.
RUN mkdir -p services/iep2_vision
COPY . services/iep2_vision/

# Top-level services package marker (not in the build context).
RUN touch services/__init__.py

EXPOSE 8002

# Daemon mode (production): reads env vars, no CLI args.
# Dev mode: override CMD with uvicorn for the FastAPI upload UI (see iep2_dev in docker-compose).
CMD ["python", "-m", "services.iep2_vision.main"]

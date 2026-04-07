FROM python:3.11-slim

WORKDIR /app

# System deps for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Pre-download YOLOv8n weights at build time so the first tracking job
# doesn't stall waiting for a network download at runtime.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" || echo "YOLO pre-download skipped (no network at build time)"

RUN mkdir -p /tmp/retailvision

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

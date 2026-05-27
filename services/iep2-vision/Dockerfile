FROM python:3.11-slim

WORKDIR /app
ENV IEP2_TEST1_DIR=/app/testing-data/Test1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ffmpeg git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY requirements.txt .
RUN pip install --no-cache-dir loguru scikit-image thop ninja tabulate tensorboard pycocotools
RUN pip install --no-cache-dir --no-deps yolox==0.3.0
RUN pip install --no-cache-dir -r requirements.txt

COPY botsort_reid.yaml ./botsort_reid.yaml
COPY app/ ./app/

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

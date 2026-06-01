FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY services/iep1_ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY services/iep1_ingestion/ ./services/iep1_ingestion/

EXPOSE 8001

CMD ["uvicorn", "services.iep1_ingestion.app.main:app", "--host", "0.0.0.0", "--port", "8001"]

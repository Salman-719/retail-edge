FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# IEP4 alert-evaluation daemon — one process per store. No HTTP port, no gRPC.
CMD ["python", "-m", "app.main"]

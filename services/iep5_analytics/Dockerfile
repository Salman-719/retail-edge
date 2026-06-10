FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# IEP5 end-of-shift analytics job — runs once to completion and exits.
# No HTTP port, no daemon. Launched per (store, shift_date) by EEP.
CMD ["python", "-m", "app.main"]

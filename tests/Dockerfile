FROM python:3.11-slim

WORKDIR /workspace

# Install test dependencies. The test code itself is mounted at runtime
# so this layer only needs to be rebuilt when requirements change.
COPY tests/e2e/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

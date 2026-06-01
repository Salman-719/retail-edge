FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Mirror module path: services.edge_agent.app.*
RUN mkdir -p services/edge_agent
COPY app/ services/edge_agent/app/
COPY proto/ services/edge_agent/proto/
RUN touch services/__init__.py services/edge_agent/__init__.py

ENTRYPOINT ["python", "-m", "services.edge_agent.app.main"]

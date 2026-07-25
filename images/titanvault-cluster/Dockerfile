# TitanVault Cluster Agent — 分布式推理编排器
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 procps libgomp1 libstdc++6 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py discovery.py node.py model_registry.py orchestrator.py ./
COPY templates/ templates/

ENV CLUSTER_AGENT_PORT=8094 \
    MODEL_DIR=/data/models \
    LLAMA_CPP_DIR=/opt/llama.cpp

EXPOSE 8094

CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8094"]

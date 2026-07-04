# Deep Research Web 应用 — QUEST-9B 驱动的深度研究
# FastAPI 后端 + 纯 HTML 前端, dashboard 风格
FROM python:3.10-slim

WORKDIR /app

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源码
COPY server.py agent.py tools.py index.html ./

# 数据卷 (报告 + session 持久化)
VOLUME ["/data/quest-reports"]

EXPOSE 8099

# host-gateway 让容器访问本机 QUEST-9B/SearXNG/LiteLLM
ENV QUEST_ENDPOINT=http://host-gateway:8093/v1
ENV SEARXNG_URL=http://host-gateway:8087
ENV LITELLM_URL=http://host-gateway:4000/v1
ENV ON_BASE_URL=http://host-gateway:5055
ENV REPORTS_DIR=/data/quest-reports
ENV MAX_TURNS=5

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8099"]

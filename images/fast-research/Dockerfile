# Fast Research Web 应用 — QUEST-9B 驱动的深度研究
# FastAPI 后端 + 纯 HTML 前端, dashboard 风格
FROM python:3.10-slim

WORKDIR /app

# 系统依赖: 中文字体 (PDF 导出需要)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源码
COPY server.py agent.py tools.py scheduler.py index.html ./

# 数据卷 (报告 + session 持久化)
VOLUME ["/data/quest-reports"]

EXPOSE 8099

# host-gateway 让容器访问本机 QUEST-9B/SearXNG/LiteLLM/mcpjungle
ENV QUEST_ENDPOINT=http://host-gateway:8093/v1
ENV SEARXNG_URL=http://host-gateway:8087
ENV LITELLM_URL=http://host-gateway:4000/v1
ENV ON_BASE_URL=http://host-gateway:5055
ENV MINERU_URL=http://host-gateway:18080
ENV MCPJUNGLE_URL=http://host-gateway:8086
ENV REPORTS_DIR=/data/quest-reports
ENV MAX_TURNS=6

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8099"]

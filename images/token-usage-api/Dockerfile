# token-usage-api — LiteLLM 用量薄代理 + 内存聚合
# 轻量纯 Python 服务: fastapi + uvicorn + httpx
FROM python:3.12-slim

WORKDIR /app

# 依赖单独一层 (先 COPY requirements 再 install), 改源码不破坏依赖缓存。
# 依赖以 requirements.txt 为唯一来源, 与镜像外开发环境一致。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY token_usage_api.py .

# 非 root 运行: 此服务持有 LITELLM_MASTER_KEY 并代理鉴权调用, 不应以 root 跑。
RUN useradd -r -u 1000 app && chown -R app /app
USER app

ENV USAGE_API_PORT=8090
EXPOSE 8090

# token_usage_api.py 暴露 /health (含上游 litellm 探活), 供 compose 做就绪/存活探测。
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8090/health',timeout=3).status==200 else 1)"

CMD ["python3", "token_usage_api.py"]

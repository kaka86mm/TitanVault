# api-discover — API 自动发现服务
# 扫 docker 容器发现暴露端口的服务, 探测 OpenAPI, 提供健康检查/测试代理
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api_discover.py index.html ./

# 需要 root: 读 docker.sock (属主 root) 做容器发现
ENV API_DISCOVER_PORT=8098
EXPOSE 8098
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8098/api/services',timeout=3).status==200 else 1)"

CMD ["python3", "api_discover.py"]

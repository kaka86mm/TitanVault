# sensevoice — FunASR ASR 封装 (转写 + 情感 + 语音事件), CPU
# Python 3.10 是 funasr/magic-pdf 生态实测稳定的版本
FROM python:3.10-slim

WORKDIR /app

# FunASR 运行所需的系统库:
#   libsndfile1     soundfile 读写音频 (sensevoice_api.py 直接调用)
#   ffmpeg          funasr 内部解码部分容器格式时的后备解码器
#   libgl1/libglib2.0-0  funasr 链路里图像处理 (doc layout 等) 依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sensevoice_api.py .

# 非 root 运行: 接收用户上传的音频文件, 最小权限原则。
RUN useradd -r -u 1000 app && chown -R app /app
USER app

ENV PORT=9991
ENV MODEL_SOURCE=modelscope
EXPOSE 9991

# sensevoice_api.py 暴露 /health, 模型懒加载导致首请求慢, 健康检查只看进程存活。
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9991/health',timeout=3).status==200 else 1)"

CMD ["python3", "sensevoice_api.py"]

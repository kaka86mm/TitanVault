"""
SenseVoice ASR API — FunASR 原生部署
支持：语音转写 + 情感识别 + 语音事件检测
端口：9991
"""
import os
import tempfile
import time
import re
import logging
import threading
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from funasr import AutoModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sensevoice-api")

app = FastAPI(title="SenseVoice FunASR API", version="2.0.0")

MODEL_DIR = os.environ.get("MODEL_DIR", "/data/models/asr")
DEVICE = os.environ.get("DEVICE", "cpu")
NCPU = int(os.environ.get("NCPU", "8"))
# 模型源: modelscope (国内, 默认) 或 hf (全球)。安装时用户选, 全局统一。
MODEL_SOURCE = os.environ.get("MODEL_SOURCE", "modelscope")

model = None
_model_lock = threading.Lock()

EMOTION_TAGS = {"HAPPY", "ANGRY", "SAD", "NEUTRAL", "SURPRISED", "FEARFUL", "DISGUSTED"}
EVENT_TAGS = {"BGM", "MUSIC", "APPLAUSE", "LAUGHTER", "COUGH", "BREATH", "NOISE", "SNEEZE", "SPEECH"}
SPECIAL_TAGS = {"withitn", "woitn"}
LANG_TAGS = {"zh", "en", "yue", "ja", "ko", "de", "fr", "es", "ru", "ar"}

TAG_RE = re.compile(r"<\|([^|>]+)\|>")


def get_model():
    """懒加载模型, 加锁防并发首请求重复加载。"""
    global model
    if model is not None:
        return model
    with _model_lock:
        if model is not None:
            return model
        # Check models exist, download from MODEL_SOURCE if missing
        for model_name, subpath in [
            ("SenseVoiceSmall", "iic/SenseVoiceSmall"),
            ("vad", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"),
        ]:
            model_path = os.path.join(MODEL_DIR, model_name)
            if not os.path.isdir(model_path) or not os.listdir(model_path):
                logger.info(f"Downloading {subpath} from {MODEL_SOURCE}...")
                if MODEL_SOURCE == "modelscope":
                    from modelscope import snapshot_download
                    snapshot_download(subpath, cache_dir=MODEL_DIR)
                else:  # hf (全球)
                    from huggingface_hub import snapshot_download as hf_download
                    hf_download(subpath, cache_dir=MODEL_DIR)

        logger.info("Loading SenseVoiceSmall + VAD...")
        t0 = time.time()
        model = AutoModel(
            model=os.path.join(MODEL_DIR, "SenseVoiceSmall"),
            vad_model=os.path.join(MODEL_DIR, "speech_fsmn_vad_zh-cn-16k-common-pytorch"),
            vad_kwargs={"max_single_segment_time": 30000},
            device=DEVICE,
            ncpu=NCPU,
            disable_update=True,
        )
        logger.info(f"Model loaded in {time.time()-t0:.1f}s")
    return model


@app.get("/")
async def root():
    return {
        "message": "SenseVoice FunASR API",
        "version": "2.0.0",
        "features": ["asr", "emotion", "event"],
        "endpoints": {
            "transcribe": "/v1/audio/transcriptions",
            "health": "/health",
            "docs": "/docs",
        },
    }


@app.get("/health")
async def health():
    return {"status": "UP", "model": "SenseVoiceSmall", "backend": "FunASR"}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="zh"),
):
    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        audio_data, sr = sf.read(tmp_path)
        duration = len(audio_data) / sr

        t0 = time.time()
        m = get_model()
        result = m.generate(
            input=tmp_path,
            language=language,
            use_itn=True,
        )
        infer_time = time.time() - t0

        raw_text = result[0]["text"] if result else ""
        text, emotion, event, language_detected = parse_labels(raw_text)

        return JSONResponse({
            "text": text,
            "emotion": emotion,
            "event": event,
            "language": language_detected,
            "raw_text": raw_text,
            "duration": round(duration, 2),
            "infer_time": round(infer_time, 3),
            "rtf": round(infer_time / duration, 3) if duration > 0 else 0,
        })
    except Exception as e:
        logger.exception("Transcription failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        os.unlink(tmp_path)


def parse_labels(raw: str) -> tuple:
    tags = TAG_RE.findall(raw)
    emotion = "NEUTRAL"
    event = ""
    language = ""

    for tag in tags:
        tag_upper = tag.upper()
        if tag_upper in EMOTION_TAGS:
            emotion = tag_upper
        elif tag_upper in EVENT_TAGS:
            event = tag_upper
        elif tag in LANG_TAGS:
            language = tag

    text = TAG_RE.sub("", raw).strip()
    return text, emotion, event, language


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9991"))
    uvicorn.run(app, host="0.0.0.0", port=port)

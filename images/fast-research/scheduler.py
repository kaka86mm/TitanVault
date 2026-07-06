"""
scheduler.py — 定时研究调度器 (APScheduler)

功能: 按间隔自动跑 fast research agent, 生成报告。
间隔选项: 每日(24h) / 每周(168h) / 每12h / 每6h / 自定义N小时

持久化: APScheduler jobstore → SQLite
        schedule 元数据 → JSON (与 session 持久化模式一致)
"""
import os
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.interval import IntervalTrigger

SCHEDULES_DIR = Path(os.environ.get("SCHEDULES_DIR",
    os.environ.get("REPORTS_DIR", "/data/quest-reports") + "/.schedules"))
SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)

JOBSTORE_DB = str(SCHEDULES_DIR / "jobs.sqlite")
METADATA_FILE = SCHEDULES_DIR / "metadata.json"

_scheduler: Optional[BackgroundScheduler] = None
_metadata: Dict[str, dict] = {}  # schedule_id → metadata

# 运行 agent 的回调 (由 server.py 注入, 避免循环导入)
_run_callback = None


def init_scheduler(run_callback):
    """初始化调度器。run_callback(session_id, question) 跑 agent。"""
    global _scheduler, _run_callback, _metadata
    _run_callback = run_callback

    # 加载元数据
    if METADATA_FILE.exists():
        try:
            _metadata = json.loads(METADATA_FILE.read_text())
        except Exception:
            _metadata = {}

    _scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{JOBSTORE_DB}")},
        timezone="Asia/Shanghai",
    )
    _scheduler.start(paused=False)


def _save_metadata():
    METADATA_FILE.write_text(json.dumps(_metadata, ensure_ascii=False, indent=2))


def _job_callback(schedule_id: str):
    """APScheduler 定时回调: 跑 agent。"""
    meta = _metadata.get(schedule_id)
    if not meta:
        return

    question = meta.get("question", "")
    if not question or not _run_callback:
        return

    # 生成 session_id (与 server.py 的格式一致)
    import uuid as uuid_lib
    sid = f"rs_{uuid_lib.uuid4().hex[:12]}"

    # 更新 last_run
    meta["last_run"] = datetime.now().isoformat()
    meta["last_session"] = sid
    _save_metadata()

    try:
        _run_callback(sid, question,
                       attachments=meta.get("attachments", []),
                       is_scheduled=True)
    except Exception as e:
        meta["last_error"] = str(e)
        _save_metadata()


# 间隔映射 (小时)
INTERVAL_MAP = {
    "daily": 24,
    "weekly": 168,
    "12h": 12,
    "6h": 6,
}


def add_schedule(question: str, interval: str = "daily",
                 focus: str = "", attachments: list = None) -> dict:
    """创建定时研究任务。

    interval: "daily" / "weekly" / "12h" / "6h" / 数字(小时)
    focus: 调优要求/关注点
    attachments: 附件列表 [{filename, md, source_type}]
    """
    import uuid as uuid_lib
    schedule_id = f"sch_{uuid_lib.uuid4().hex[:12]}"

    # 解析间隔
    if isinstance(interval, str) and interval in INTERVAL_MAP:
        hours = INTERVAL_MAP[interval]
    else:
        try:
            hours = int(interval)
        except (ValueError, TypeError):
            hours = 24  # 默认每日

    full_question = question
    if focus:
        full_question = f"{question}\n\n[调优要求]: {focus}"

    # 存元数据
    meta = {
        "schedule_id": schedule_id,
        "question": full_question,
        "original_question": question,
        "focus": focus,
        "interval_label": interval,
        "interval_hours": hours,
        "attachments": attachments or [],
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "last_session": None,
        "last_error": None,
        "active": True,
    }
    _metadata[schedule_id] = meta
    _save_metadata()

    # 注册 APScheduler job
    _scheduler.add_job(
        _job_callback,
        trigger=IntervalTrigger(hours=hours),
        args=[schedule_id],
        id=schedule_id,
        replace_existing=True,
    )

    return meta


def list_schedules() -> List[dict]:
    """列出所有定时任务。"""
    return sorted(_metadata.values(),
                  key=lambda x: x.get("created_at", ""),
                  reverse=True)


def remove_schedule(schedule_id: str) -> bool:
    """删除定时任务。"""
    if schedule_id not in _metadata:
        return False
    try:
        _scheduler.remove_job(schedule_id)
    except Exception:
        pass
    del _metadata[schedule_id]
    _save_metadata()
    return True


def pause_schedule(schedule_id: str) -> bool:
    """暂停定时任务。"""
    if schedule_id not in _metadata:
        return False
    try:
        _scheduler.pause_job(schedule_id)
        _metadata[schedule_id]["active"] = False
        _save_metadata()
        return True
    except Exception:
        return False


def resume_schedule(schedule_id: str) -> bool:
    """恢复定时任务。"""
    if schedule_id not in _metadata:
        return False
    try:
        _scheduler.resume_job(schedule_id)
        _metadata[schedule_id]["active"] = True
        _save_metadata()
        return True
    except Exception:
        return False


def shutdown_scheduler():
    """关闭调度器。"""
    if _scheduler:
        _scheduler.shutdown(wait=False)

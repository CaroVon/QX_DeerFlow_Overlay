"""QX backend HTTP 访问层：声明式工具（qx_tools.pipeline / qx_tools.design）共用。

单用户工作区模式：401 时经 /auth/bootstrap 匿名签发 token 并重放一次。
显式设置过 RAINFOREST/DB 等环境变量优先；本模块只做传输，不含业务逻辑。
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

QX_API_BASE = os.environ.get("QX_API_BASE", "http://localhost:8000").rstrip("/")
QX_API_PREFIX = f"{QX_API_BASE}/api/v1"

_TOKEN: str | None = None
# 服务间认证（R4）：与 QX 后端共享 QX_SERVICE_KEY；用户身份优先取当前线程 owner
# （langgraph runnable 上下文 → gateway sqlite threads_meta），回退 QX_SERVICE_USER。
QX_SERVICE_KEY = os.environ.get("QX_SERVICE_KEY", "")
QX_SERVICE_USER = os.environ.get("QX_SERVICE_USER", "admin@deerflow.qxdev.com")
DEERFLOW_DB_PATH = os.environ.get(
    "DEERFLOW_DB_PATH",
    "/home/administrator/dev/agents/qx-deerflow/deer-flow/backend/.deer-flow/data/deerflow.db",
)

# thread_id → owner email 进程级缓存（TTL 简化为永久——线程归属不变）
_OWNER_CACHE: dict[str, str | None] = {}


def _thread_owner_email() -> str | None:
    """当前 langgraph 线程的 owner email（拿不到上下文返回 None）。"""
    try:
        from langchain_core.runnables import ensure_config

        thread_id = (ensure_config().get("configurable") or {}).get("thread_id")
        if not thread_id:
            return None
        if thread_id in _OWNER_CACHE:
            return _OWNER_CACHE[thread_id]
        import sqlite3
        from pathlib import Path

        db = Path(DEERFLOW_DB_PATH)
        if not db.is_file():
            return None
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT u.email FROM threads_meta t JOIN users u ON u.id = t.user_id "
                "WHERE t.thread_id = ?",
                (thread_id,),
            ).fetchone()
        finally:
            conn.close()
        email = row[0] if row else None
        _OWNER_CACHE[thread_id] = email
        return email
    except Exception:  # noqa: BLE001 —— 身任传播失败回退默认服务身份
        return None


def _current_user() -> str:
    return _thread_owner_email() or QX_SERVICE_USER


def _current_thread_id() -> str | None:
    """当前 langgraph 线程 ID（无上下文返回 None）。"""
    try:
        from langchain_core.runnables import ensure_config

        return (ensure_config().get("configurable") or {}).get("thread_id")
    except Exception:  # noqa: BLE001
        return None


def _service_headers() -> dict[str, str]:
    if not QX_SERVICE_KEY:
        return {}
    headers = {
        "X-QX-Service-Key": QX_SERVICE_KEY,
        "X-QX-User": _current_user(),
    }
    tid = _current_thread_id()
    if tid:
        headers["X-QX-Thread"] = str(tid)[:64]
    return headers


def _bootstrap_token(client: httpx.Client) -> str | None:
    try:
        resp = client.post("/auth/bootstrap")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token") or data.get("access_token")
    except Exception as exc:  # noqa: BLE001
        logger.warning("QX auth bootstrap failed: %s", exc)
    return None


def request(method: str, path: str, **kwargs) -> httpx.Response:
    """QX API 请求：优先服务密钥认证；未配置时回退 bootstrap token（401 自动签发重放一次）。"""
    global _TOKEN
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_service_headers())
    if not QX_SERVICE_KEY and _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    with httpx.Client(base_url=QX_API_PREFIX, headers=headers, timeout=60.0) as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code == 401 and not QX_SERVICE_KEY and not _TOKEN:
            _TOKEN = _bootstrap_token(client)
            if _TOKEN:
                client.headers["Authorization"] = f"Bearer {_TOKEN}"
                resp = client.request(method, path, **kwargs)
        return resp


def public_file_url(file_url: str | None) -> str | None:
    """/api/v1/files/* → /api/qx/files/*（DeerFlow 同源可点开的形式）。"""
    if not file_url:
        return None
    return file_url.replace("/api/v1/files/", "/api/qx/files/", 1)

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
    """带单用户 bootstrap 认证的 QX API 请求（401 自动签发重放一次）。"""
    global _TOKEN
    headers = {"Authorization": f"Bearer {_TOKEN}"} if _TOKEN else {}
    with httpx.Client(base_url=QX_API_PREFIX, headers=headers, timeout=60.0) as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code == 401 and not _TOKEN:
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

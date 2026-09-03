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
# 服务间认证（R4）：与 QX 后端共享 QX_SERVICE_KEY；用户身份暂为 admin，
# W3-4 用户贯通后由线程 owner 注入（contextvar 或按线程工具实例）。
QX_SERVICE_KEY = os.environ.get("QX_SERVICE_KEY", "")
QX_SERVICE_USER = os.environ.get("QX_SERVICE_USER", "admin@deerflow.qxdev.com")


def _service_headers() -> dict[str, str]:
    if not QX_SERVICE_KEY:
        return {}
    return {
        "X-QX-Service-Key": QX_SERVICE_KEY,
        "X-QX-User": QX_SERVICE_USER,
    }


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

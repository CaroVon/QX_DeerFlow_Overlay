"""qx-mcp 直连模式（Phase 2 v1）：绕过 QX FastAPI，直接与 Celery broker / Postgres 交互。

进程边界说明：本模块只在 qx-mcp 的 stdio 子进程内使用——该进程不 import
deerflow，因此可以安全地持有 QX 的 ``app.*`` 导入路径约定（与 deer-flow
gateway 的 ``app`` 包不共进程，无命名冲突）。

v1 范围：submit（建行 + send_task）/ status（直读 DB）/ cancel（revoke + 置败）。
审批门（approve/reject）仍走 QX API（业务语义收敛单点，Phase 2 v2 再下沉）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("qx-mcp.direct")

_TASK_NAME = "app.tasks.product_studio_tasks.run_product_studio_pipeline"


def _qx_backend_dir() -> Path:
    return Path(os.environ.get("QX_BACKEND_DIR", Path.home() / "dev" / "agents" / "QX_product_agent" / "backend"))


def _load_qx_env() -> None:
    """把 QX backend/.env 的关键连接配置装进进程环境（不覆盖已有值）。"""
    env_file = _qx_backend_dir() / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in {"DATABASE_URL", "CELERY_BROKER_URL"} and value and key not in os.environ:
            os.environ[key] = value


def _sync_db_url() -> str:
    _load_qx_env()
    url = os.environ.get("DATABASE_URL", "postgresql://qx:qx@localhost:5432/qx")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    elif url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return url


def _engine():
    from sqlalchemy import create_engine

    return create_engine(_sync_db_url(), pool_pre_ping=True, future=True)


def _celery_app():
    from celery import Celery

    _load_qx_env()
    broker = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    app = Celery("qx_direct", broker=broker, backend=None)
    app.conf.broker_transport_options = {"protocol": 2}
    return app


def submit_direct(idea: str) -> dict:
    """建 studio_products 行（幂等：idea_hash 命中则复用）并投递 Celery 任务。"""
    from sqlalchemy import text

    normalized = " ".join(idea.split())
    if not normalized:
        return {"error": "empty idea"}
    idea_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    product_id = str(uuid.uuid4())

    with _engine().begin() as conn:
        row = conn.execute(
            text("SELECT id, status FROM studio_products WHERE idea_hash = :h LIMIT 1"),
            {"h": idea_hash},
        ).fetchone()
        if row is not None:
            product_id = str(row[0])
            if str(row[1]) in {"running", "queued", "waiting_approval"}:
                return {"job_id": product_id, "status": str(row[1]), "reused": True}
        else:
            conn.execute(
                text(
                    "INSERT INTO studio_products (id, idea, idea_hash, status, node_status, created_at, updated_at)"
                    " VALUES (:id, :idea, :h, 'queued', '{}', :now, :now)"
                ),
                {"id": product_id, "idea": normalized, "h": idea_hash, "now": now},
            )

    result = _celery_app().send_task(_TASK_NAME, args=[product_id])
    return {"job_id": product_id, "status": "queued", "celery_task_id": result.id, "reused": False}


def status_direct(job_id: str) -> dict:
    from sqlalchemy import text

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, error_message, asset_package, progress_log, node_status FROM studio_products WHERE id = :i"
            ),
            {"i": job_id},
        ).fetchone()
    if row is None:
        return {"error": "not found"}
    status, error_message, package_raw, progress_raw, node_status_raw = row
    try:
        package = json.loads(package_raw) if package_raw else {}
    except json.JSONDecodeError:
        package = {}
    # 运行中：node_status 在表列；暂停/完成：快照在 asset_package 里。取并集。
    node_status: dict = {}
    for source in (node_status_raw, package.get("node_status")):
        if not source:
            continue
        try:
            parsed = json.loads(source) if isinstance(source, str) else dict(source)
        except (json.JSONDecodeError, TypeError):
            continue
        node_status.update({k: v for k, v in parsed.items() if v})
    paused_node = package.get("_paused_node")
    if not paused_node and status == "waiting_approval" and error_message and "节点:" in error_message:
        paused_node = error_message.split("节点:", 1)[1].strip()
    progress_tail = []
    for line in (progress_raw or "").splitlines()[-5:]:
        try:
            progress_tail.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {
        "job_id": job_id,
        "status": str(status),
        "paused_node": paused_node,
        "node_status": node_status,
        "error_message": error_message,
        "progress_tail": progress_tail,
    }


def cancel_direct(job_id: str) -> dict:
    from sqlalchemy import text

    with _engine().begin() as conn:
        row = conn.execute(
            text("SELECT celery_task_id, status FROM studio_products WHERE id = :i"), {"i": job_id}
        ).fetchone()
        if row is None:
            return {"error": "not found"}
        task_id, status = row
        if task_id:
            try:
                _celery_app().control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception as exc:  # noqa: BLE001
                logger.warning("revoke failed: %s", exc)
        conn.execute(
            text(
                "UPDATE studio_products SET status = 'failed',"
                " error_message = '产品流水线已取消（qx-mcp direct）', updated_at = :now WHERE id = :i"
            ),
            {"i": job_id, "now": datetime.now(timezone.utc)},
        )
    return {"job_id": job_id, "cancelled": True}

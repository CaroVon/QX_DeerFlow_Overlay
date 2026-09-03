#!/usr/bin/env python
"""完整管线测试：真实提交 QX Studio 任务，自动过审批门，跑到终态。

- 提交/查询：qx-mcp direct 模式（Celery + Postgres 直交）
- 审批门：QX API approve-node（业务语义单点）
- 输出：JSON 摘要（stdout 最后一行）+ 过程日志

用法：.venv/bin/python scripts/full_pipeline_test.py "<product idea>" [timeout_minutes]
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "qx_mcp"))
os.environ.setdefault("QX_MCP_MODE", "direct")

from qx_mcp import _direct  # noqa: E402

import httpx  # noqa: E402

QX_API = os.environ.get("QX_API_BASE", "http://localhost:8000").rstrip("/") + "/api/v1"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def approve(job_id: str, node: str) -> bool:
    with httpx.Client(base_url=QX_API, timeout=30) as c:
        r = c.post(f"/product/{job_id}/approve-node", json={"node": node})
    log(f"approve({node}) -> {r.status_code} {r.text[:120]}")
    return r.status_code == 200


def main() -> int:
    idea = sys.argv[1] if len(sys.argv) > 1 else "Compact ultralight camping hammock with integrated bug net for backpackers"
    timeout_min = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    deadline = time.time() + timeout_min * 60

    sub = _direct.submit_direct(idea)
    log(f"submit -> {sub}")
    job_id = sub.get("job_id")
    if not job_id:
        print(json.dumps({"error": "submit failed", "detail": sub}, ensure_ascii=False))
        return 1

    approved: set[str] = set()
    final = None
    while time.time() < deadline:
        time.sleep(30)
        s = _direct.status_direct(job_id)
        status = s.get("status")
        node = s.get("paused_node")
        nodes = s.get("node_status") or {}
        done = [k for k, v in nodes.items() if v == "completed"]
        log(f"status={status} nodes_done={len(done)} paused={node}")
        if status == "waiting_approval" and node and node not in approved:
            if approve(job_id, node):
                approved.add(node)
            else:
                time.sleep(10)  # 状态可能尚未落库，下轮重试
            continue
        if status in {"completed", "failed", "cancelled"}:
            final = s
            break
    else:
        final = _direct.status_direct(job_id)
        final["note"] = f"timeout after {timeout_min}min"

    summary = {"idea": idea, "job_id": job_id, "final": final, "stage_durations": _stage_durations(job_id)}
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if final and final.get("status") == "completed" else 2


def _stage_durations(job_id: str) -> dict[str, float]:
    """从 progress_log（JSONL 时间戳）统计各节点耗时（分钟），供性能回归对照。"""
    from datetime import datetime

    from sqlalchemy import text

    durations: dict[str, float] = {}
    started: dict[str, datetime] = {}
    try:
        with _direct._engine().connect() as conn:
            row = conn.execute(
                text("SELECT progress_log FROM studio_products WHERE id = :i"), {"i": job_id}
            ).fetchone()
        for line in (row[0] or "").splitlines() if row and row[0] else []:
            try:
                ev = json.loads(line)
                ts = datetime.fromisoformat(ev["ts"])
                node, st = ev.get("node"), ev.get("status")
                if st == "running" and node not in started:
                    started[node] = ts
                elif st == "completed" and node in started:
                    durations[node] = round((ts - started.pop(node)).total_seconds() / 60, 1)
            except (ValueError, KeyError, TypeError):
                continue
    except Exception as exc:  # noqa: BLE001 —— 摘要失败不影响主流程
        durations["_error"] = str(exc)[:120]
    return durations


if __name__ == "__main__":
    raise SystemExit(main())

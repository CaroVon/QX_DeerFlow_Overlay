#!/usr/bin/env python
"""完整管线测试：真实提交 QX Studio 任务，自动过审批门，跑到终态。

- 提交/状态/审批/取消：qx_tools.pipeline 声明式工具（HTTP + 服务密钥）
- 输出：JSON 摘要（stdout 最后一行，含分阶段耗时）+ 过程日志

用法：（先 source deer-flow/.env 提供 QX_API_BASE/QX_SERVICE_KEY）
  .venv/bin/python scripts/full_pipeline_test.py "<product idea>" [timeout_minutes]
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "qx_tools"))

from qx_tools import qxhttp  # noqa: E402
from qx_tools.pipeline import (  # noqa: E402
    approve_studio_gate_tool,
    get_studio_job_status_tool,
    submit_studio_job_tool,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    idea = sys.argv[1] if len(sys.argv) > 1 else "Compact ultralight camping hammock with integrated bug net for backpackers"
    timeout_min = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    deadline = time.time() + timeout_min * 60

    sub = json.loads(submit_studio_job_tool.invoke({"idea": idea}))
    log(f"submit -> {sub}")
    job_id = sub.get("job_id")
    if not job_id:
        print(json.dumps({"error": "submit failed", "detail": sub}, ensure_ascii=False))
        return 1

    approved: set[str] = set()
    final = None
    while time.time() < deadline:
        time.sleep(30)
        s = json.loads(get_studio_job_status_tool.invoke({"job_id": job_id}))
        status = s.get("status")
        node = s.get("paused_node")
        done = [k for k, v in (s.get("node_status") or {}).items() if v == "completed"]
        log(f"status={status} nodes_done={len(done)} paused={node}")
        if status == "waiting_approval" and node and node not in approved:
            r = approve_studio_gate_tool.invoke({"job_id": job_id, "node": node})
            log(f"approve({node}) -> {str(r)[:120]}")
            if '"http": 200' in str(r):
                approved.add(node)
            else:
                time.sleep(10)  # 状态可能尚未落库，下轮重试
            continue
        if status in {"completed", "failed", "cancelled"}:
            final = s
            break
    else:
        final = json.loads(get_studio_job_status_tool.invoke({"job_id": job_id}))
        final["note"] = f"timeout after {timeout_min}min"

    summary = {"idea": idea, "job_id": job_id, "final": final, "stage_durations": _stage_durations(job_id)}
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if final and final.get("status") == "completed" else 2


def _stage_durations(job_id: str) -> dict[str, float]:
    """从 /logs 事件流统计各节点耗时（分钟），供性能回归对照。"""
    durations: dict[str, float] = {}
    started: dict[str, datetime] = {}
    try:
        resp = qxhttp.request("GET", f"/product/{job_id}/logs")
        for ev in ((resp.json() or {}).get("logs") or []) if resp.status_code == 200 else []:
            try:
                ts = datetime.fromisoformat(str(ev["ts"]).replace("Z", "+00:00"))
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

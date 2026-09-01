#!/usr/bin/env bash
# QX × DeerFlow 集成冒烟测试套件（Phase 5 质量门）
#
# 前置：gateway(8001)/frontend(3000)/nginx(2026)/QX栈(8000) 均在运行。
# 用法：bash scripts/smoke.sh [base_url]
#   base_url 默认 http://localhost:2026（经 nginx 的统一入口）
set -uo pipefail

BASE="${1:-http://localhost:2026}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DF_BACKEND="$ROOT/deer-flow/backend"
PASS=0; FAIL=0; SKIP=0

ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }
skip() { echo "  - $1 (skip)"; SKIP=$((SKIP+1)); }

echo "════ QX × DeerFlow 冒烟测试 ════  base=$BASE"

# ─── 1. 服务健康 ───────────────────────────────────────────
echo "[1/7] 服务健康"
curl -sf --max-time 6 "$BASE/health" | grep -q healthy && ok "gateway /health" || bad "gateway /health"
curl -sf --max-time 8 -o /dev/null "$BASE/" && ok "frontend root" || bad "frontend root"
curl -sf --max-time 6 "$BASE/api/qx/auth/me" -o /dev/null && ok "qx-api /api/qx/auth/me（nginx 叠加路由）" || bad "qx-api /api/qx"

# ─── 2. 工具解析（DeerFlow resolve_variable 路径）───────────
echo "[2/7] 工具注册"
cd "$DF_BACKEND" && "$DF_BACKEND/.venv/bin/python" - <<'PY' && ok "4 个 qx 工具可解析" || bad "工具解析失败"
from deerflow.reflection import resolve_variable
from langchain.tools import BaseTool
for p in (
    "qx_tools.amazon:collect_amazon_data_tool",
    "qx_tools.amazon:competitor_matrix_tool",
    "qx_tools.knowledge:knowledge_search_tool",
    "qx_tools.knowledge:knowledge_ingest_tool",
):
    resolve_variable(p, BaseTool)
PY

# ─── 3. MOD 工具（mock 数据，离线）────────────────────────
echo "[3/7] MOD 工具（mock）"
MOD_RESULT=$("$DF_BACKEND/.venv/bin/python" - <<'PY' 2>/dev/null
import json
from qx_tools.amazon import collect_amazon_data_tool
r = json.loads(collect_amazon_data_tool.invoke({"keyword": "smoke test mouse", "source": "mock", "top_n": 6}))
assert r["n_products"] >= 1, "no products"
print(r["n_products"])
PY
) && ok "collect_amazon_data mock（$MOD_RESULT 竞品）" || bad "collect_amazon_data mock"

# ─── 4. 知识库工具（ingest → search 召回）──────────────────
echo "[4/7] 知识库工具"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" "$DF_BACKEND/.venv/bin/python" - <<'PY' 2>/dev/null && ok "knowledge ingest→search 召回" || bad "knowledge 工具链"
from qx_tools.knowledge import knowledge_ingest_tool, knowledge_search_tool
import time
knowledge_ingest_tool.invoke({"text": "冒烟测试标记：等离子空气净化的核心卖点在于无滤网与低噪音，目标客群为母婴家庭。", "url": "https://smoke.qx.local"})
time.sleep(1)
r = knowledge_search_tool.invoke({"query": "冒烟测试标记 等离子"})
assert "冒烟测试标记" in r, "no recall: " + r[:200]
PY

# ─── 5. qx-mcp 直连模式（submit/status/cancel）────────────
echo "[5/7] qx-mcp 直连（Celery+PG 直交）"
MCP_RESULT=$(QX_MCP_MODE=direct "$DF_BACKEND/.venv/bin/python" - <<'PY' 2>/dev/null
import os, json, time
from qx_mcp import server
# 唯一 idea：避免与历史取消/失败记录幂等碰撞导致任务守卫拒绝重跑
idea = f"smoke direct-mode test {time.strftime('%Y%m%d%H%M%S')}: silicone foldable funnel kit"
r = json.loads(server.submit_studio_job(idea))
assert r.get("job_id"), r
time.sleep(5)
s = json.loads(server.get_studio_job_status(r["job_id"]))
assert s.get("status") in {"queued", "running", "waiting_approval"}, s
c = json.loads(server.cancel_studio_job(r["job_id"]))
assert c.get("cancelled"), c
print("ok")
PY
) && ok "direct submit→status→cancel" || bad "direct mode: $MCP_RESULT"

# ─── 6. Agent E2E（经 gateway API 让 agent 调用 qx 工具）────
echo "[6/7] agent E2E（gateway 驱动）"
cd /tmp && rm -f smoke-cookies.txt
LOGIN=$(curl -sf --max-time 10 -X POST "$BASE/api/v1/auth/login/local" \
  -H "Origin: $BASE" -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=admin@deerflow.qxdev.com' --data-urlencode 'password=QxAdmin2026!' \
  -c smoke-cookies.txt) || { bad "登录失败（先运行 scripts/init-admin）"; }
if [ -n "${LOGIN:-}" ]; then
  ok "登录 + CSRF"
  # 登录链路完整性：cookie → /workspace 认证通过（307 到 chats/new 属正常跳转）→ 页面 200
  LOC=$(curl -s --max-time 15 -b smoke-cookies.txt -D - -o /dev/null "$BASE/workspace" | grep -i "^location:" | tr -d '\r' | awk '{print $2}')
  if [ "$LOC" = "/workspace/chats/new" ]; then
    curl -sf --max-time 15 -b smoke-cookies.txt -o /dev/null "$BASE/workspace/chats/new" && ok "登录链路（cookie→workspace 认证→页面 200）" || bad "workspace/chats/new 页面"
  else
    bad "登录链路：/workspace 重定向到 ${LOC:-无}（期望 /workspace/chats/new；/login 表示会话被拒）"
  fi
  CSRF=$(grep csrf_token smoke-cookies.txt | awk '{print $NF}')
  TID=$(curl -sf --max-time 10 -X POST "$BASE/api/threads" -b smoke-cookies.txt \
    -H "Origin: $BASE" -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{}' \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['thread_id'])") || TID=""
  if [ -n "$TID" ]; then
    ok "创建线程 $TID"
    curl -sf --max-time 180 -X POST "$BASE/api/threads/$TID/runs/wait" -b smoke-cookies.txt \
      -H "Origin: $BASE" -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
      -d '{"input":{"messages":[{"role":"user","content":"调用 collect_amazon_data_tool，keyword=smoke e2e keyboard，source=mock，top_n=5，只回复 JSON 结果里的 n_products 数字。"}]}}' \
      > /tmp/smoke-agent-run.json 2>/dev/null
    python3 -c "
import json, sys
d = json.load(open('/tmp/smoke-agent-run.json'))
called = any(tc['name'] == 'collect_amazon_data_tool'
             for m in d.get('messages', []) if m.get('type') == 'ai'
             for tc in (m.get('tool_calls') or []))
final = [str(m.get('content')) for m in d.get('messages', [])
         if m.get('type') == 'ai' and not m.get('tool_calls') and str(m.get('content','')).strip()]
assert called, 'agent 未调用工具'
assert any('5' in t for t in final), 'agent 未汇报结果: ' + str(final)[:200]
" && ok "agent 调用 MOD 工具并汇报" || bad "agent E2E"
  else
    bad "创建线程失败"
  fi
fi

# ─── 7. SSE 流式（事件可达）────────────────────────────────
echo "[7/7] SSE 流式"
SSE=$(curl -sN --max-time 60 -X POST "$BASE/api/threads/$TID/runs/stream" -b /tmp/smoke-cookies.txt \
  -H "Origin: $BASE" -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
  -d '{"input":{"messages":[{"role":"user","content":"回复：ok"}]},"stream_mode":["updates"]}' 2>/dev/null | head -2)
echo "$SSE" | grep -q "event: metadata" && ok "SSE metadata 事件" || bad "SSE 流式"

# ─── 汇总 ──────────────────────────────────────────────────
echo "════ 结果: $PASS 通过 / $FAIL 失败 / $SKIP 跳过 ════"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)

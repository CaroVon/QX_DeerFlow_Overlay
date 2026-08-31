#!/usr/bin/env bash
# 一键重启 gateway：append 日志（不覆盖历史）、健康等待。
# 用法：bash scripts/restart-gateway.sh [--frontend]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DF="$ROOT/deer-flow"

kill_port() {
    ss -tlnp 2>/dev/null | grep ":$1" | grep -oP 'pid=\K[0-9]+' | sort -u | xargs -r kill
    for _ in $(seq 1 10); do
        ss -tln 2>/dev/null | grep -q ":$1 " || return 0
        sleep 1
    done
    ss -tlnp 2>/dev/null | grep ":$1" | grep -oP 'pid=\K[0-9]+' | sort -u | xargs -r kill -9
}

start_gateway() {
    (cd "$DF/backend" \
        && set -a && source ../.env && set +a \
        && export DEER_FLOW_PROJECT_ROOT="$DF" DEER_FLOW_HOME="$DF/backend/.deer-flow" \
        && nohup .venv/bin/python -m uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 \
            >> "$DF/logs/gateway.log" 2>&1 &)
    for i in $(seq 1 30); do
        curl -sf --max-time 3 http://localhost:8001/health >/dev/null 2>&1 && { echo "✓ gateway 就绪 (${i}s)"; return 0; }
        sleep 1
    done
    echo "✗ gateway 30s 未就绪，查 $DF/logs/gateway.log"; return 1
}

start_frontend() {
    (cd "$DF/frontend" && nohup pnpm run dev >> "$DF/logs/frontend.log" 2>&1 &)
    for i in $(seq 1 40); do
        curl -sf --max-time 3 -o /dev/null http://localhost:3000/ && { echo "✓ frontend 就绪 (${i}s)"; return 0; }
        sleep 1
    done
    echo "✗ frontend 40s 未就绪，查 $DF/logs/frontend.log"; return 1
}

mkdir -p "$DF/logs"

echo "==> 重启 gateway ..."
kill_port 8001
start_gateway

if [ "${1:-}" = "--frontend" ]; then
    echo "==> 重启 frontend ..."
    kill_port 3000
    start_frontend
fi
echo "完成。统一入口: http://localhost:2026"

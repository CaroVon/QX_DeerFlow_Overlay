#!/usr/bin/env bash
# 把 qx 包以 editable 方式装进 deer-flow 的后端 venv（不改 deer-flow 任何文件）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DF_BACKEND="$ROOT/deer-flow/backend"

[ -d "$DF_BACKEND" ] || { echo "未找到 $DF_BACKEND，请先克隆 deer-flow（见 README）"; exit 1; }
[ -x "$HOME/.local/bin/uv" ] || { echo "未找到 uv，请先安装：https://docs.astral.sh/uv/"; exit 1; }

cd "$DF_BACKEND"
for pkg in qx-tools qx-core qx-mcp; do
    echo "==> editable install: $pkg"
    uv pip install -e "$ROOT/packages/${pkg//-/_}" 2>/dev/null \
        || uv pip install -e "$ROOT/packages/$pkg"
done

echo "==> 验证工具可解析（DeerFlow 的 resolve_variable 路径）"
"$DF_BACKEND/.venv/bin/python" - <<'PY'
from deerflow.reflection import resolve_variable
from langchain.tools import BaseTool

for path in (
    "qx_tools.amazon:collect_amazon_data_tool",
    "qx_tools.amazon:competitor_matrix_tool",
):
    t = resolve_variable(path, BaseTool)
    print(f"OK  {path}  (name={t.name})")
PY
echo "完成。"

#!/usr/bin/env bash
# 上游同步：deer-flow 子模块跟随 bytedance/deer-flow 官方发布。
#
# 约定：
# - deer-flow/ 保持零源码改动；本地只生成运行时配置
#   （config.yaml / extensions_config.json，上游 .gitignore 已忽略）。
# - 升级 = 切到新 tag → 重新跑本仓库 scripts/install.sh → make config-upgrade
#   → 跑 deer-flow 测试与我们的冒烟验证。
# - 季度升级窗口；每次升级先读上游 CHANGELOG.md 的 breaking 段。
set -euo pipefail

TAG="${1:?用法: sync-upstream.sh <tag>   例: v2.1.0}"
cd "$(dirname "${BASH_SOURCE[0]}")/../deer-flow"

git fetch --tags origin
git checkout -q "$TAG"
echo "已切换到 $TAG"
echo "后续步骤："
echo "  1. bash ../scripts/install.sh          # 重新 editable 安装 qx 包"
echo "  2. cd backend && uv sync               # 上游依赖"
echo "  3. make config-upgrade                 # 合并新增配置字段"
echo "  4. 对比 config.example.yaml 的 tools:/mcpServers: 段，确认 qx 条目仍兼容"

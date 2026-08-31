"""qx-mcp：QX Product Studio 的 MCP 服务（stdio）。

把 QX studio 管线封装为 submit / status / cancel 三个 MCP 工具，
供 DeerFlow（extensions_config.json → mcpServers）以 stdio 方式拉起。
Phase 2 v0 采用适配器模式：转发到现役 QX FastAPI（默认 http://localhost:8000），
后续 Phase 2 v1 将替换为原生 Celery worker 直迁（qx-jobs），接口不变。
"""

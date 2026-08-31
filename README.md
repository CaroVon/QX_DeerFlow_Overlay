# qx-deerflow — QX Product Studio × DeerFlow v2 集成工作区

把 QX Product Studio（亚马逊产品研究 → 策略/PRD → 演示 → PPT 交付）嵌入
[bytedance/deer-flow](https://github.com/bytedance/deer-flow) v2 框架，
以 DeerFlow 为壳、QX 为插件生态，目标是流畅可用的商用产品。

## 核心原则

1. **deer-flow/ 保持零源码改动**——只通过官方扩展点接入（`config.yaml → tools:`、
   `extensions_config.json → mcpServers`、skills），升级时无 rebase 成本。
2. **QX 侧只做"适配仓库"的改造**，不要求 DeerFlow 适配 QX。
3. 最大化保留 DeerFlow 生态：开发环境（make/uv/pnpm）、测试矩阵、认证、部署形态。

## 目录结构

```
qx-deerflow/
├── deer-flow/        # 上游 clone，锁定 tag（当前 v2.0.0），零源码改动
├── packages/         # 我们的 uv workspace
│   └── qx_tools/     # DeerFlow 工具：亚马逊采集 / MOD 竞品矩阵
├── skills/custom/    # DeerFlow 技能包：amazon-product-studio
├── scripts/
│   ├── install.sh    # editable 安装 qx 包进 deer-flow venv + 工具解析验证
│   └── sync-upstream.sh  # 上游升级流程（季度窗口）
└── runtime/          # QX 产物输出（QX_OUTPUT_DIR 默认值）
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `QX_SOURCES_DIR` | `~/dev/agents` | QX 源码平铺根（含 amazon_matrix_mod 等） |
| `QX_OUTPUT_DIR` | `<repo>/runtime/outputs` | QX 工具产物落盘目录 |
| `QX_MOD_SOURCE` | `rainforest` | MOD 数据源默认值（`mock` 可离线演示） |
| `DEEPSEEK_API_KEY` 等 | - | 由 deer-flow `config.yaml` 以 `$VAR` 引用 |

## 仓库配对（克隆指引）

本仓（QX_DeerFlow_Overlay）不含 deer-flow 目录（已 gitignore）。完整环境：

```bash
git clone https://github.com/CaroVon/QX_DeerFlow_Overlay.git qx-deerflow
cd qx-deerflow
git clone https://github.com/CaroVon/QX_DeerFlow.git deer-flow   # 已含 QX 前端适配的快照仓
cp config-templates/config.yaml.qx deer-flow/config.yaml
cp config-templates/extensions_config.json deer-flow/extensions_config.json
cp config-templates/.env.example deer-flow/.env   # 填入真实密钥
bash scripts/install.sh
```

QX_DeerFlow 为 bytedance/deer-flow v2.0.0 的源码快照 + QX 集成改动（上游完整历史因网络限制未携带；
如需上游同步基线，可 `git remote add upstream https://github.com/bytedance/deer-flow.git` 后按
scripts/sync-upstream.sh 流程操作）。

## 快速开始

```bash
# 1. 上游依赖（backend 已 uv sync / frontend 已 pnpm install 的可跳过）
cd deer-flow && make install

# 2. 安装 qx 包 + 验证工具解析
bash scripts/install.sh

# 3. 生成运行时配置（首次：复制 config.yaml 并确认 tools: 段含 qx 条目）
cd deer-flow && cp -n config.example.yaml config.yaml || true

# 4. 启动（开发模式）
cd deer-flow && make dev
```

## 与上游版本相关的重要事实（选型依据）

- v2.0.0（当前锁定）支持：`tools:` 声明式挂载第三方 BaseTool、MCP servers、skills。
- v2.0.0 **不含**：`deerflow-extension-api` 插件契约、MCP `task_toolsets` 长任务契约
  （均为未发布 main 分支特性）。因此：
  - Phase 2 长任务 = MCP server 普通工具（submit/status/cancel 三件套 + 技能层轮询）
  - Phase 3 业务 API = 独立 FastAPI 服务（qx-api）经 nginx 路由叠加挂载
  - 升级到 ≥2.1 发布版后可平移到官方 plugin router / task_toolsets 契约

## 上游同步

见 `scripts/sync-upstream.sh` 头部注释：季度窗口、先读 CHANGELOG breaking 段、
升级后重跑 install + config-upgrade + 冒烟。

## 路线图（与主方案一致）

- [x] Phase 0 基线：deer-flow v2.0.0 跑通（gateway 8001 + frontend 3000 + nginx 2026）
- [x] Phase 1a 工具层：qx-tools（MOD 采集/矩阵）——agent E2E 验证通过
- [x] Phase 1b 数据层：qx-core（rag 五模块抽取 + knowledge_search/ingest 工具）——agent E2E 验证通过
- [x] Phase 2 v0 长任务适配器：qx-mcp http 模式——agent E2E 验证通过
- [x] Phase 2 v1 长任务直连：qx-mcp direct 模式（Celery broker + Postgres 直交，
  send_task 按名投递，approve 门仍走 QX API 收敛语义）
- [x] Phase 3 业务 API：nginx 叠加路由 `/api/qx/*` → QX `/api/v1/*`（隧道域名可达）
- [x] Phase 4a 聊天内审批：qx-mcp 新增 approve/reject_studio_gate + paused_node 自动检测
  （核心流程可在 DeerFlow 聊天内完成；SPA 组件移植为后续渐进项）
- [x] Phase 5 质量门：`scripts/smoke.sh`（7 组 11 项冒烟）+ `docker-compose.qx.yml` 拓扑固化
- [ ] Phase 4b 前端组件级融合（DSL 渲染器/资产卡片移植进 Next.js，Konva/GrapesJS 后置）
- [ ] Phase 2 v2 审批门语义下沉到 qx-jobs（彻底脱离 QX FastAPI）

## 当前运行拓扑（本机验证态）

| 入口 | 地址 | 说明 |
|---|---|---|
| 统一入口 | http://localhost:2026 | nginx 容器（df-nginx，端口发布 + host-gateway 桥接） |
| 前端 | http://localhost:3000 | DeerFlow Next.js dev（.env 直连 8001） |
| Gateway | http://localhost:8001 | deer-flow backend（uvicorn，无 reload） |
| QX 现役栈 | http://localhost:8000 | QX FastAPI + Celery（qx-mcp 的适配后端） |

已验证的 E2E 链路：
1. agent 调 `collect_amazon_data_tool`（mock）→ 返回竞品摘要并正确汇报
2. agent 调 `qx-studio_submit/get_status/cancel` → 现役 QX 管线入队/运行/取消

## 上游前端覆盖清单（UI 适配，供 rebase 对照）

用户授权对 deer-flow 前端做产品适配（框架/范式严格遵循上游）。已改文件：

| 文件 | 改动 |
|---|---|
| `frontend/src/app/layout.tsx` | metadata：DeerFlow → QX Studio |
| `frontend/src/components/workspace/workspace-header.tsx` | 侧边栏品牌：DeerFlow/DF → QX Studio/QX（视觉框架不变） |
| `frontend/src/components/workspace/workspace-nav-chat-list.tsx` | 新增 QX Studio 导航项（沿用 SidebarMenuButton+Link 范式） |
| `frontend/src/app/workspace/qx/page.tsx` | **新增**：QX Studio 页面入口 |
| `frontend/src/components/workspace/qx/qx-studio-panel.tsx` | **新增**：任务列表/节点进度/审批门/产物下载（TanStack Query 状态机感知轮询，移植自 QX SPA） |

后端（deer-flow/backend）仍保持零源码改动。

## 稳定性与速度专项（本轮落地 + 后续规划）

**已落地**：
- 登录修复：持久化 `AUTH_JWT_SECRET`/`BETTER_AUTH_SECRET`（此前临时密钥随重启轮换，会话全部失效——"登录后即被弹回"的根因）；smoke 增加登录链路断言。
- 持久化：config.yaml `database.backend: sqlite`（线程/运行记录跨重启保留）。
- 日志：`scripts/restart-gateway.sh`（append 日志 + 健康等待，替代裸 kill+nohup）。
- **PPT 落盘 /mnt/d → /home**：根因是 8/28 旧会话启动的长驻 worker 持有搬家前 Settings（9P 挂载慢、曾致 D 态）；已重启 worker，验证新任务全部落 /home。
- **PPT 并发 4 → 6**：start_all.sh 默认值上调（上限 MAX=6，429 自动降并发兜底不变）。

**后续规划（按优先级）**：
1. **命名 Cloudflare 隧道**（需 `cloudflared tunnel login` 授权一次）：固定域名 + `--restart unless-stopped` 自愈，替代 quick tunnel 的域名漂移与无 SLA。
2. **进程监管容器化**：gateway/frontend 迁入 docker compose（`docker/docker-compose.qx.yml` 已含 nginx/env 骨架，补服务定义），替代 nohup。
3. **前端生产模式常驻**：`pnpm build && pnpm start` 替代 dev（dev 无优化、首包大；对应 QX vite manualChunks 防白屏的同类诉求）；dev 仅开发时用。
4. **WSL DNS 抖动**：已两次挂死关键路径（bge 模型加载、uv 安装）；建议 systemd-resolved 缓存 + 备用 nameserver。
5. **MOD 0-credit 回放引导**：skill 中已提示复用 data_dir；后续在工具层加显式 reuse 参数透传。
6. **失败节点级重跑**：GatePause + PostgresSaver 断点已验证，规划 UI/API 级"从失败节点续跑"替代全量重试（QX 已有 regenerate 端点可复用）。

## 实施备忘（踩坑记录）

- **模型配置**：`langchain_openai:ChatOpenAI` 用 `base_url` 而非 `api_base`
  （后者是 `deerflow.models.patched_deepseek` 家族的参数名；配错会泄漏到 SDK 调用报
  `unexpected keyword argument 'api_base'`）。
- **包名冲突**：QX 根包名 `app` 与 deer-flow gateway 包 `app` 冲突，
  qx 包绝不能把 `QX_product_agent/` 根目录加进 sys.path（只加平铺的
  amazon_matrix_mod / agent-platform 等所在目录）。
- **WSL Docker**：`--network host` 拿到的是 docker VM 网络而非 WSL 发行版；
  nginx 容器需 `-p 2026:2026 --add-host=host.docker.internal:host-gateway`
  + 叠加配置改 upstream（见 docker/nginx-qx.conf，由上游 nginx.local.conf 生成）。
- **FastMCP**（当前 mcp SDK 版本）：`@mcp.tool()` 返回原函数，直接调用即可测试。
- **uv run 会回滚 uv pip 装的包**：`uv run` 按 lockfile 同步环境，会把 `uv pip install`
  的扩展（torch/celery/redis 等）视作多余卸载或长时间锁定环境。**凡是操作这个共享
  venv 的进程一律用 `.venv/bin/python` 直调**（gateway 启动、smoke.sh、install.sh 均如此）。
- **bge 嵌入模型**：首次加载需联网（设 `HF_ENDPOINT=https://hf-mirror.com`）；模型缓存
  后设 `HF_HUB_OFFLINE=1` 避免 DNS 抖动挂死（两值均已写入 deer-flow/.env 与 smoke.sh）。
- **kombu + 缺 redis 包**：deer-flow venv 默认不含 redis-py，celery broker 直连前需
  `uv pip install redis==4.6.0`（与 QX 侧验证组合一致）。

## 测试入口

```bash
bash scripts/smoke.sh                              # 7 组 11 项冒烟（含 agent E2E/SSE/直连模式）
deer-flow/backend/.venv/bin/python scripts/full_pipeline_test.py "<idea>" 100
                                                    # 真实全管线（自动过审批门，100 分钟上限）
```

# 交互式多 Agent 协作小说创作系统

一个基于 **LangGraph** 编排、**FastAPI** 提供 REST/SSE 接口、**Vue 3** 提供前端的交互式小说创作系统。系统由多个专职 Agent 协作完成「世界观构建 → 剧情生成 → 内部质控 → 人工审核 → 全文整合」的完整创作闭环，并通过 LLM 流式输出与服务器推送事件（SSE）实现逐 token 的前端实时渲染。

> 本文档为面向开发者与部署者的项目说明，所有内容以当前源码（`src/`、`server.py`、`configs/`、`frontend/`、`tests/`）为准，并尽量保留源码中的 docstring 与设计注释。
>
> 若需快速了解设计取舍与踩坑记录，另可参考 `docs/项目经验总结.md`（注意：文档中引用的 `docs/supervisor_说明.md` 当前并不存在，相关内容以 `src/agents/supervisor.py` 源码注释为准）。

---

## 目录

1. [项目简介](#1-项目简介)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [安装与环境配置](#4-安装与环境配置)
5. [配置说明](#5-配置说明)
6. [Agent 详解](#6-agent-详解)
7. [状态管理](#7-状态管理--graphstatepy)
8. [工具层](#8-工具层)
9. [流式输出（SSE）](#9-流式输出sse--srcutilsstreamingpy)
10. [API 接口](#10-api-接口--serverpy)
11. [数据库与持久化](#11-数据库与持久化)
12. [前端结构详解](#12-前端结构详解--frontendsrc)
13. [知识库入库（RAG）](#13-知识库入库rag)
14. [测试](#14-测试)
15. [运行](#15-运行)
16. [常见问题](#16-常见问题)
17. [已知限制与技术债](#17-已知限制与技术债)

---

## 1. 项目简介

用户只需输入一句创作需求（例如「写一篇赛博朋克背景下的侦探小说」），系统便会：

1. 自动检索资料、生成世界观设定、角色与规则；
2. 逐段推进剧情，每轮给出多个分支选项供用户选择或自由输入；
3. 内置 Critic Agent 对设定与每段剧情做一致性 / 合规 / 风险审查，低分时中断交由人工确认（Human-in-the-Loop）；
4. 用户可随时回溯、要求重来或生成全文；
5. 最终由 Integrator Agent 将全部片段润色整合为完整小说；
6. 已完成的会话会被持久化为「长期记忆」，支持后续续写。

整个流程由 LangGraph 的有状态图（`StateGraph`）驱动，支持断点续跑（checkpoint）与 Human-in-the-Loop（`interrupt`）。服务主体为异步协程（`async def` + `graph.ainvoke` / `graph.astream_events`）。**注意**：虽然服务是异步的，但部分工具/存储仍是同步阻塞实现（见 [§17 已知限制](#17-已知限制与技术债)），单条会话内部各 Agent 节点**串行编排**，多会话之间借由事件循环实现 I/O 并发。

---

## 2. 系统架构

### 2.1 整体数据流

数据流分两层理解：**（A）主流程编排**——LangGraph 内 5 个节点如何按阶段推进，以及在哪里暂停等用户；**（B）外部依赖**——每个节点在运行中会调用哪些工具与外部存储。

#### （A）主流程编排（节点之间的关系）

按「阶段」从上往下读。实线为正常推进，蓝线为「打回重做 / 等待用户」回环，红色为「人工审核暂停点（`interrupt`）」。

```
 用户输入
   │  POST /api/sessions 或 /action 或 SSE /stream?action=
   ▼
┌──────────────────────── FastAPI (server.py) ────────────────────────┐
│  graph.ainvoke / astream_events  →  转 SSE 推送前端（见 §9）          │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │  进入 LangGraph StateGraph（入口：supervisor）
                                 ▼
            ┌──────────────── 阶段 1：初始化 ────────────────┐
            │  supervisor（解析意图 + 路由）                  │
            │     │  current_phase = init                   │
            │     ▼                                          │
            │  world_builder（搜索 + 生成世界观/角色/规则） │
            │     │  current_phase = world_building          │
            │     ▼                                          │
            │  critic（审查【设定】）                         │
            │     │ 通过/达上限 ──▶ supervisor                │
            │     └──不通过且低分 ──▶ interrupt(setting_review) ═ 等人工 ═
            │              （驳回 → critic_loop → world_builder 重生成）          │
            └─────┬──────────────────────────────────────────┘
                  │ 设定通过
                  ▼
            ┌──────────── 阶段 2：等待用户确认世界观 ──────────┐
            │  supervisor ── 调 interrupt(setting_confirm) ◀══ 红线：人工确认 │
            │  （批准 → story_progressing；驳回 → 清空设定重生成）              │
            └─────────┬──────────────────────────────────────┘
                      │ 用户批准
                      ▼
            ┌──────────── 阶段 3：逐轮写剧情 ──────────────────┐
            │  story_driver（生成一段剧情 + 分支选项）          │
            │     │  awaiting_user=True                        │
            │     ▼                                           │
            │  critic（审查【剧情片段】）                      │
            │     │ 通过/达上限 ──▶ supervisor                 │
            │     └──不通过且低分 ──▶ interrupt(segment_review) ═ 等人工 ═      │
            │              （驳回 → critic_loop → story_driver 重写并回滚）      │
            │     ▼  supervisor（有 options → interrupt(choice) 等用户选分支）  │
            │  （用户选 A/B/C / 自由输入 / 生成全文 / 回溯）                    │
            └─────────┬───────────────────────────────────────┘
                      │ 用户选择「生成全文」/ 已完成
                      ▼
            ┌──────────── 阶段 4：收尾 ────────────────────────┐
            │  integrator（拼接润色 → final_output）            │
            │     │  current_phase = completed → supervisor    │
            │     ▼  supervisor → done → END                   │
            │  并触发长期记忆持久化（见 §11.3）                 │
            └──────────────────────────────────────────────────┘
```

> 回环说明：`critic → story_driver`/`world_builder`（蓝线）与 `supervisor → supervisor`（红线 `interrupt`）是图的两条主要回边；前者由 `critic_route` 触发，后者由 `supervisor_route` 在 `awaiting_user=True` 时触发。具体判定见 §2.2。

#### （B）外部依赖（节点 ↔ 工具 / 存储的关系）

每个节点的「产出」依赖于下列外部能力；持久化全部落在同一 `novel.db`（见 §11）。

```
                 supervisor               world_builder            story_driver            critic              integrator
                    │                        │                        │                      │                    │
       解析用户输入 │            ┌───────────┴─────────┐   ┌──────────┴───────┐   ┌────────┴───────┐  ┌────────┴───────┐
       路由/interrupt│            │  search_tool       │   │ memory 工具      │   │ memory 工具    │  │ （仅读状态，   │
                    │            │  (Bing MCP 搜索)    │   │ (角色/线索/伏笔) │   │ (读取记忆)    │  │   无外部依赖） │
                    │            └───────────┬─────────┘   │ rag_tool         │   └────────┬───────┘  └────────┬───────┘
                    │                        │             │ (ChromaDB+Rerank)│            │                    │
                    │                        │             └────────┬─────────┘            │                    │
                    │                        │                      │                     │                    │
                    └────────────────────────┴──────────────────────┴─────────────────────┴────────────────────┘
                                         │                      │                     │
                                         ▼                      ▼                     ▼
                              ┌──────────────────────────────────────────────────────────────┐
                              │             novel.db（SQLite，多表同库）                       │
                              │  • checkpointer 表  → 断点续跑 / interrupt 恢复               │
                              │  • session_metas 表 → 会话元数据（session_store.py）          │
                              │  • long_term_memories 表 → 已完成会话续写（long_term_memory） │
                              └──────────────────────────────────────────────────────────────┘
                              ┌──────────────────────────────────────────────────────────────┐
                              │   外部服务（非本库）：Bing MCP 搜索、ChromaDB+Rerank、LLM API │
                              └──────────────────────────────────────────────────────────────┘
```

### 2.2 图节点与路由（`src/graph/workflow.py` + `src/agents/supervisor.py`）

`workflow.py` 通过 `StateGraph(NovelState)` 注册 5 个节点，并以条件边串起调度逻辑；`build_graph_async()` 用 `AsyncSqliteSaver(aiosqlite.connect(get_db_path()))` 编译图（详见 §11）。

**固定的普通边（无条件）：**

| 起点 | 终点 | 说明 |
| --- | --- | --- |
| （入口） | `supervisor` | `set_entry_point("supervisor")` |
| `world_builder` | `critic` | 设定生成后必过质控 |
| `story_driver` | `critic` | 剧情生成后必过质控 |
| `integrator` | `supervisor` | 整合完成后回到 supervisor 收尾（`done`） |

**图的 5 个节点：**

| 节点 | 来源 | 职责 |
| --- | --- | --- |
| `supervisor` | `agents/supervisor.py` | 调度中心：解析用户输入、路由、在等待用户输入时调用 `interrupt` 暂停图 |
| `world_builder` | `agents/researcher.py` | 调用 Bing 搜索 + LLM 生成世界观设定 / 角色 / 规则 |
| `story_driver` | `agents/writer.py` | 根据历史、记忆、RAG 检索生成下一段剧情与分支选项 |
| `critic` | `agents/reviewer.py` | 内部质控：审查设定或剧情片段，低分时 `interrupt` 人工审核 |
| `integrator` | `agents/integrator.py` | 拼接所有片段并润色输出完整小说 |

> 关于 supervisor 的设计取舍（源码注释）：项目**没有**使用 LangGraph 官方 `langgraph.prebuilt.create_supervisor`，而是自研了一个更轻量的版本，理由有三——① 避免每次都调用 LLM 解析用户输入以节省成本；② 让解析逻辑更可控、便于自定义规则和多级降级；③ 让路由逻辑更清晰、便于调试与维护。

**两条条件边路由（均为纯函数，只读取 state 返回节点名，无副作用）：**

- `supervisor_route(state)`（`supervisor.py` 末尾）：图执行完 `supervisor_node` 后的阶段总控路由，依据 `current_phase` 决定下一个节点：
  - `init` → `world_builder`
  - `world_building`：`setting_confirmed` 为真 → `story_driver`；`world_setting` 为空 → 继续 `world_builder`；已构建未确认 → 回 `supervisor` 等待确认
  - `story_progressing`：`awaiting_user` 为真 → 回 `supervisor`（在 `interrupt` 处暂停）；否则 → `story_driver`（已收到输入 / 续写新会话）
  - `critic_loop`：`human_approval == "rejected"` → `story_driver` 打回重写；否则 → `critic`
  - `completed` → `integrator`
  - `done` → `END`
  - 其它兜底 → `supervisor`
- `critic_route(state)`（`supervisor.py` 末尾）：审查节点后的路由：
  - 世界观审查（无 `current_segment` 但有 `world_setting`）：`current_phase == "critic_loop"` → `world_builder`（被驳回后重生成）；否则 → `supervisor`（交回等待世界观确认）
  - 剧情审查：`current_phase == "critic_loop"` → `story_driver`（被驳回后重写）；否则 → `supervisor`（等待用户选分支）

---

## 3. 目录结构

```
I don't write novels/
├── server.py                  # FastAPI 主入口：REST + SSE 接口、静态文件托管、lifespan
├── pyproject.toml             # Python 依赖（langgraph / fastapi / langchain 生态等）
├── README.md                  # 本文档
├── 需求文档.md                # 原始需求说明
├── novel.db / .db-shm / .db-wal   # SQLite 持久化文件（checkpointer / 元数据 / 长期记忆）
│
├── configs/                   # 配置目录（唯一配置来源）
│   ├── settings.yaml          # 默认配置（llm / story / quality / rag / misc）
│   └── .env                   # （需自行创建）最高优先级环境变量（API Key / Chroma / Bing 等）
│
├── docs/
│   └── 项目经验总结.md         # 设计取舍与踩坑记录（中文）
│
├── knowledge_base/            # RAG 知识库目录（当前为空，上传/批量入库后产生文档）
│
├── src/                       # Python 后端核心（见下表细分）
│   ├── __init__.py
│   ├── graph/                 # LangGraph 图定义
│   ├── agents/                # 5 个专职 Agent 节点
│   ├── tools/                 # 工具层（记忆 / RAG / 搜索 / 文档 / 长期记忆）
│   ├── prompts/               # 各 Agent 的 Prompt 模板
│   ├── utils/                 # 基础设施（配置 / 数据库 / LLM / 日志 / 会话存储 / 流式）
│   └── logs/                  # 运行时日志输出目录
│
├── frontend/                  # Vue 3 前端（见 §12）
│   ├── index.html
│   ├── package.json           # 依赖：vue / element-plus / three / axios / vite
│   ├── vite.config.js         # dev 端口 5173，/api 代理到 localhost:8001
│   ├── dist/                  # 生产构建产物（server.py 会挂载此目录）
│   └── src/
│       ├── App.vue            # 主应用（会话流、流式渲染、审核面板、3D 场景）
│       ├── main.js
│       ├── api/client.js      # 后端 API 封装（含 SSE EventSource）
│       ├── components/
│       │   ├── SessionSidebar.vue   # 会话侧边栏（新建/选择/重命名/删除/续写）
│       │   ├── PaperScene.vue       # Three.js 3D 纸张场景
│       │   └── Button3D.vue         # Three.js 3D 按钮
│       └── styles/main.css
│
└── tests/                     # 测试
    ├── test_agents_fixes.py   # Agent 修复相关用例
    └── test_server_routes.py  # 服务端路由用例
```

`src/` 细分：

| 子目录 | 文件 | 作用 |
| --- | --- | --- |
| `graph/` | `state.py` | `NovelState`（`TypedDict`）全局状态定义 |
| | `workflow.py` | `StateGraph` 注册节点 + 固定边/条件边 + `build_graph_async()` |
| `agents/` | `supervisor.py` | 调度中心：意图解析 + 路由 + `interrupt` |
| | `researcher.py` | `world_builder_node`：世界观/角色/规则生成 |
| | `writer.py` | `story_driver_node`：剧情 + 分支选项生成 |
| | `reviewer.py` | `critic_node`：内部质控 + 人工审核中断 |
| | `integrator.py` | `integrator_node`：全文整合 |
| `tools/` | `memory.py` | 剧情记忆（角色/线索/伏笔/时间线） |
| | `rag_tool.py` | RAG 检索（ChromaDB + Reranker + TTL 缓存） |
| | `search_tool.py` | Bing MCP 搜索 |
| | `document_util.py` | 文档加载/分割（RAG 入库） |
| | `long_term_memory.py` | 长期记忆持久化（续写） |
| `prompts/` | `supervisor/researcher/writer/reviewer/integrator_prompt.py` | 各 Agent 的 Prompt 模板 |
| `utils/` | `config.py` | 配置加载（`.env` > `settings.yaml` > 默认值） |
| | `database.py` | `novel.db` 路径与业务表初始化 |
| | `llm.py` | LLM 调用封装（`llm_call`） |
| | `logger.py` | 日志配置（`setup_logger`） |
| | `session_store.py` | 会话元数据 CRUD（同步） |
| | `streaming.py` | SSE 事件转换（`transform_graph_events` / `format_sse_event`） |

> **与旧文档的差异提醒**：旧 README 提到的 `src/graph/edges.py`、`src/graph/nodes.py`、`src/app.py`、根目录 `config.py`、`tools/`、`utils/` 根目录镜像目录、`exchange_rag_agent/` 目录，以及 `docs/supervisor_说明.md`，**经核查当前均不存在或已移除**。实际图/节点/边逻辑集中在 `src/graph/workflow.py` 与 `src/agents/supervisor.py`；命令行交互入口当前不存在（见 §15）。

---

## 4. 安装与环境配置

### 4.1 后端（Python ≥ 3.11）

```bash
# 在项目根目录（含 pyproject.toml）
pip install -e .
# 或
pip install -r <(pip-compile pyproject.toml 2>/dev/null)   # 也可用 uv： uv pip install -e .
```

依赖见 `pyproject.toml`，核心包括：`langgraph>=1.0`、`langgraph-checkpoint-sqlite`、`fastapi`、`uvicorn`、`pydantic`、`sse-starlette`、`openai`、`mcp`、`langchain-chroma` / `langchain-community` / `langchain-openai` / `langchain-text-splitters`、`pymupdf`（PDF）、`docx2txt`（Word）、`python-multipart`（文件上传）。

> `langgraph-checkpoint-postgres` 也在依赖中声明，但当前代码**仅实现 SQLite 后端**（见 §11.1 / §17）。

### 4.2 前端

```bash
cd frontend
npm install
npm run dev      # 开发模式，默认 http://localhost:5173
# 或 npm run build && npm run preview  # 生产构建
```

生产模式下 `server.py` 会尝试挂载 `frontend/dist` 作为静态文件（见 `server.py` 中 `StaticFiles` 挂载，失败则静默跳过，走开发模式）。

### 4.3 可选服务

- **ChromaDB**（RAG 检索）：默认 `localhost:8081`。需自行部署 Chroma 服务（或使用本地 persist 模式，取决于 `CHROMA_HOST/CHROMA_PORT` 配置）。
- **Bing MCP 搜索**：通过 `configs/.env` 中的 `mcp_bing_config` 配置（见 §5.2）。未配置时系统自动跳过搜索，不影响主流程。
- **LLM / Embedding / Rerank 服务**：通过 OpenAI 兼容接口访问，默认示例为 SiliconFlow。

---

## 5. 配置说明

配置优先级：**`configs/.env` 环境变量 > `configs/settings.yaml` > 代码默认值**。`src/utils/config.py` 统一 `load_dotenv(configs/.env)`，并读取 `settings.yaml` 作后备默认。注意：**`.env` 唯一来源是 `configs/.env`**（与 `rag_tool.py`、`search_tool.py` 一致），根目录不存在独立 `.env`，且 `configs/settings.yaml` 仅作默认值后备。

### 5.1 `configs/settings.yaml`

```yaml
llm:
  openai_api_key: ""          # OpenAI / 兼容接口 API Key
  openai_base_url: ""         # 自定义基址（如 SiliconFlow、本地 vLLM）
  model: ""                   # 模型名，如 gpt-4o / Qwen 系列
  max_tokens: 2048

story:
  segment_length: 300         # 每轮片段字数
  options_count: 3            # 选项数量（不含自由输入）

quality:
  max_internal_iterations: 3  # Critic 内部最大循环次数
  pass_threshold: 6           # Critic 通过阈值（满分 10）
  temperature_creative: 0.8   # 创作类 Agent 温度
  temperature_critic: 0.3     # 审查类 Agent 温度

rag:
  chroma_host: "localhost"
  chroma_port: 8081
  chroma_collection: "default"
  embedding_model: "BAAI/bge-m3"
  rerank_model: "BAAI/bge-reranker-v2-m3"
  retrieve_k: 20              # 向量检索候选数
  rerank_top_k: 5             # 重排序后保留数
  cache_ttl: 300              # RAG 结果缓存 TTL（秒）

misc:
  max_backtrack_steps: 5      # 最大回溯步数
  mcp_bing_enabled: true      # 是否启用 Bing MCP 搜索
```

`src/utils/config.py` 会把 `settings.yaml` 对应键路径读成默认值，再用同名环境变量覆盖（详见 `config.py` 中的 `_yaml_val`）。

### 5.2 `configs/.env`（覆盖优先级最高）

```env
# LLM（OpenAI 兼容，示例使用 SiliconFlow）
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash

# RAG / Embedding（注意 rag_tool 内 EMBEDDING/RERANK 复用 OPENAI_API_KEY / OPENAI_BASE_URL）
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_BASE_URL=https://api.siliconflow.cn/v1   # Rerank 接口基址（rag_tool.py 读取）
CHROMA_HOST=localhost
CHROMA_PORT=8081
CHROMA_COLLECTION=default

# Bing 搜索 MCP（JSON 字符串）
# 云端 streamable_http：
mcp_bing_config={"type":"streamable_http","url":"https://..."}
# 或本地 stdio：
# mcp_bing_config={"type":"stdio","command":"npx","args":["bing-cn-mcp-enhanced"]}

# 日志
LOG_DIR=logs
LOG_LEVEL=DEBUG
```

> 注：当前持久化固定使用项目根目录的 SQLite 文件 `novel.db`（见 §11），未提供 `DATABASE_URL` / PostgreSQL 切换开关。

---

## 6. Agent 详解

### 6.1 Supervisor（调度中心）— `agents/supervisor.py`

它是整个 LangGraph 图的**入口节点**与**路由大脑**，不直接创作内容，只负责理解用户意图、维护会话阶段、在等待用户时用 `interrupt` 暂停图，并把控制权交给正确的下一节点。

**核心函数拆解：**

- `parse_user_input(user_input, phase)`：采用**多级降级**策略把一句话输入解析成动作类型（`select_option` / `free_input` / `backtrack` / `generate_full` / `confirm_setting` / `modify_setting` 等），逐级尝试、成本递增：
  1. 特殊指令精确匹配（如「生成全文」「结束」「回到上一步」「回溯」）— 零成本；
  2. `world_building` 阶段的 A/B 确认（A=确认设定 / B=修改设定）；
  3. 通用选项字母（A/B/C/D…）直接映射为 `select_option`；
  4. `COMMON_RULES` 关键词正则（「继续」「不行」「确认」「写完整」等），规则优先、零成本；
  5. 兜底走 LLM 解析（`ROUTE_PROMPT`，低温 0.3）；
  6. 终极兜底 `free_input`，保证函数永远返回合法路由、图不会因解析失败而崩溃。

  > 设计意图：自研此解析而非每次都让 LLM 判断，是为了「节省成本 + 规则可控 + 多级降级 + 便于调试」。

- `handle_backtrack(state)`：处理「回到上一步」。**三道防线**拒绝非法回溯——① 无历史可回；② 处于首轮（`current_turn ≤ 1`）；③ 已达 `MAX_BACKTRACK_STEPS` 上限（`segment_history` 长度 ≥ 上限）。通过校验后，从 `segment_history` 弹出最近一段，并同步恢复 `story_segments` / `current_segment` / `current_options`，`current_turn` 减 1，并置 `awaiting_user=True`。
- `_get_resume_input(state)`：屏蔽 LangGraph 中断恢复（`__resume__`）和自定义字段（`user_input` / `resume`）两种来源的差别，按优先级取出并转字符串；用 `is not None` 正确保留合法的空字符串输入，取不到则返回 `None`。
- `_apply_user_choice(state, user_input)`：把解析后的动作写回状态。`backtrack` → 交给 `handle_backtrack`；`generate_full` → `current_phase="completed"`（交由路由进入 integrator）；其它 → 在 `user_choices` 追加一条选择记录，并置 `awaiting_user=False` / `current_phase="story_progressing"` / `iteration_count=0`。
- `supervisor_node(state)`：图入口节点，按 `current_phase` 推进：
  - `init`：空更新，移交 `supervisor_route` → `world_builder`；
  - `world_building`：有 `world_setting` 且未确认时，构造 `kind="setting_confirm"` 的审核载荷并 `interrupt(...)` 等待用户批准/驳回；批准后 `setting_confirmed=True` / `current_phase="story_progressing"`，驳回则清空 `world_setting` 并回到 `world_building`；
  - `story_progressing`：若上一条 `user_choices` 是 `generate_full` → `completed`；若无 `current_options`（新会话或续写刚启动）→ 空更新交回 `story_driver` 生成；否则构造 `kind="choice"` 的面板并 `interrupt(...)` 等待用户输入，恢复后 `_apply_user_choice` 继续；
  - `completed` → `done`。
- `supervisor_route(state)` / `critic_route(state)`：两条条件边路由函数（见 §2.2），都是**纯函数**——只读取 state、返回字符串目标节点名，不做任何副作用，便于单测与调试。

**输入**：`NovelState`（主要读 `current_phase` / `current_options` / `user_request` / `current_turn` / `human_approval`）。
**输出**：局部状态更新（动作解析结果、`user_choices` 追加、`human_approval` 复位等），并在适当时机触发 `interrupt`。

### 6.2 World Builder（世界观构建）— `agents/researcher.py`

`world_builder_node(state)` 是**创作链路的第一道内容生产节点**，产出自洽的世界观、角色与规则，供后续剧情与审查消费。

**执行步骤：**

1. **空输入守卫**：若 `user_request` 为空，直接返回 `{"current_phase": "done"}`，避免空需求进入后续流程。
2. **背景资料检索**：调用 `search_for_world_building(user_request)`（见 §8.3）。
   - 有结果 → 拼为 `【搜索参考资料】\n{search_results}` 作为 `search_context`；
   - **无结果（MCP 未配置或检索失败）→ `search_context` 退化为空串**，不阻断主流程（可降级）。
3. **驳回反馈回带**：若 `state["critique"]` 非空（即上一次设定被 Critic 驳回），将其作为 `【上一次驳回反馈（必须针对性修改）】` 注入 Prompt，避免原样重生成同样的设定。
4. **LLM 生成设定**：用 `WORLD_BUILDER_PROMPT`（`src/prompts/researcher_prompt.py`）格式化，把 `user_request` 与 `search_context` + `revision_feedback` 注入；调用 `llm_call(..., temperature=TEMPERATURE_CREATIVE, max_tokens=2048)`。
5. **JSON 解析（容错）**：用正则 `\{.*\}` 提取首个 JSON 块并 `json.loads`；解析失败时 `data={}`，对应字段回退为空，保证节点不抛异常。
6. **返回状态**：写入 `world_setting` / `characters` / `rules`，并置 `current_phase="world_building"`、`setting_confirmed=False`、`current_turn=0`。

**输入**：读 `user_request` / `critique`（驳回反馈）。
**输出**：`world_setting`、`characters`、`rules`、`current_phase`、`setting_confirmed`、`current_turn`。
→ 之后由 `supervisor_route` 决定：未确认则回 `supervisor` 等待确认，确认后流转到 `story_driver`（审查通过）或仍是 `world_builder`（设定为空需重生成）。

### 6.3 Story Driver（剧情推进）— `agents/writer.py`

`story_driver_node(state)` 是**每轮剧情的核心生成节点**，把世界观、历史、记忆、RAG 素材综合成「一段剧情 + 多个分支选项 + 记忆增量」。

**执行步骤：**

1. **轮次与历史**：`turn = current_turn + 1`；取 `story_segments[-3:]` 拼成 `story_history`（近 3 段上下文，`"暂无"` 兜底）；用最近一条 `user_choices` 构造 `current_context`（如「用户选择了：…」）。
2. **角色描述**：把 `characters` 格式化为 `姓名（角色）：性格` 列表，空则「无」。
3. **记忆上下文**：调用 `build_memory_context(memory, current_turn=...)`，按 §8.1 的滑动窗口裁剪（仅保留近期出现的角色 / 待回收伏笔 / 近期时间线），控制 token。
4. **RAG 检索**：`retrieve_for_writing(world_setting=..., story_history=..., current_context=..., user_input=...)`（见 §8.2），把世界观关键词 + 当前上下文 + 用户输入拼成 query 检索；空结果回退为「（无参考素材）」。
5. **构造 Prompt**：`STORY_DRIVER_PROMPT`（`src/prompts/writer_prompt.py`）注入上述全部上下文，`segment_length=SEGMENT_LENGTH`、`options_count=OPTIONS_COUNT`。
6. **LLM 生成**：`llm_call(..., temperature=TEMPERATURE_CREATIVE, max_tokens=2048)`，user_prompt 为「第 N 轮剧情：继续推进故事。」。
7. **JSON 解析（容错）**：正则提取 `{...}` → `segment` / `options` / `memory_updates`；解析失败则三者为空/空列表/空字典。
8. **选项补 id**：遍历 `options`，缺 `id` 的按 `A, B, C…`（`chr(65+i)`）自动补唯一 id。
9. **状态更新**：
   - `story_segments` 追加 `segment`；
   - `segment_history` 追加 `{turn, segment, options}`（供回溯）；
   - `memory`：首次为空则 `create_initial_memory(characters)` 初始化，否则 `apply_updates(memory, memory_updates, turn)` 合并记忆增量；
   - 置 `current_segment` / `current_options` / `current_turn=turn` / `current_phase="story_progressing"` / `awaiting_user=True`。

**输入**：`user_request` / `characters` / `rules` / `world_setting` / `memory` / `user_choices` / `story_segments` / `current_turn`。
**输出**：本轮 `segment`、`options`、`memory_updates`、以及上述状态字段，并标记 `awaiting_user=True` 等待用户选择 → 经 `supervisor` 的 `interrupt` 暂停，用户选择后回到 `story_driver` 或 `critic`。

### 6.4 Critic（内部质控）— `agents/reviewer.py`

`critic_node(state)` 是**内部质控关卡**，在设定生成后、以及每轮剧情生成后触发，负责一致性/合规/风险审查，低分时把决策权交回人工（Human-in-the-Loop）。源码注释强调做了防死循环机制：生成次数超过阈值则动态降低阈值，动态阈值降为零时转人工审核。

**节点入口分流（`critic_node`）：**

- 无 `current_segment` 但存在 `world_setting` → 走 `_review_setting`（设定审查）；
- 有 `current_segment` → 走 `_review_segment`（剧情片段审查）；
- 两者皆无 → 直接返回 `{"current_phase": "story_progressing"}`（无内容可审，放行）。

**两个审查子函数共用同一套逻辑：**

- **动态阈值**：`effective_threshold = max(PASS_THRESHOLD - iteration_count, 1)`（下限 **1**）。阈值随 `iteration_count` 递增而递减——越审越宽松，避免无限循环。
- **LLM 审查**：`CRITIC_PROMPT`（`src/prompts/reviewer_prompt.py`）注入 `world_setting` / `characters` / `rules` / 待审内容 / `pass_threshold=effective_threshold`；`llm_call(..., temperature=TEMPERATURE_CRITIC, max_tokens=1024)`。解析出 `score` / `passed` / `suggestion` / `issues` / `risk_warnings`。
- **结果写入**：`critique`（建议）、`critique_score`（分数）、`risk_warnings`（风险警告）。
- **Human-in-the-Loop 中断**：当 `not passed and score < effective_threshold and iteration_count < max_internal_iterations` 时：
  - 设定审查：构造 `kind="setting_review"` 的审核载荷并 `interrupt(review_data)`；
  - 剧情审查：构造 `kind="segment_review"` 的审核载荷并 `interrupt(review_data)`；
  - 用户选择 **approved** → `human_approval="approved"`，进入 `story_progressing`（设定审查还会置 `setting_confirmed=True`）；
  - 用户选择 **rejected** → `human_approval="rejected"`、`current_phase="critic_loop"`、`iteration_count + 1`，打回重生成；**剧情审查的驳回还会调用 `_rollback_last_segment(state)` 回滚上一段已写内容**（防止重写后出现重复、轮次虚增）。
- **未触发中断的分支**（通过 或 已达最大迭代）：`passed or iteration_count >= max_internal_iterations` → 放行（`story_progressing` / 设定审查置 `setting_confirmed=False` 交由 supervisor 走确认面板）；否则进入 `critic_loop` 并 `iteration_count + 1`（自动要求 Agent 重生成，剧情审查同样会回滚上一段）。
  > 注意：达到 `max_internal_iterations` 时**跳过 `interrupt` 直接放行**，防止卡死在人工确认上。

**输入**：`current_segment` / `world_setting` / `characters` / `rules` / `current_options` / `iteration_count` / `max_internal_iterations`。
**输出**：`critique` / `critique_score` / `risk_warnings` / `human_approval` / `current_phase` / `setting_confirmed`（设定审查）/ `iteration_count`，以及选项上的 `risk_level` 标注（供前端/用户判断风险）。

### 6.5 Integrator（全文整合）— `agents/integrator.py`

`integrator_node(state)` 是**创作闭环的收尾节点**，在 `current_phase == completed` 时把零散片段润色成完整可读的小说正文。

**执行步骤：**

1. **空内容守卫**：若 `story_segments` 为空，直接返回 `{"current_phase": "done", "final_output": "暂无内容。"}`。
2. **素材拼接**：
   - `choices_text`：把 `user_choices` 拼成「第 N 轮：…」列表（无则「无」）；
   - `char_text`：角色格式化为「姓名(角色):性格」；
   - `segments_text`：所有 `story_segments` 以 `\n\n---\n\n` 分隔，逐段标注「第 i+1 段」。
3. **构造 Prompt**：`INTEGRATOR_PROMPT`（`src/prompts/integrator_prompt.py`）注入上述拼接结果。
4. **LLM 润色**：`llm_call(..., temperature=TEMPERATURE_CREATIVE, max_tokens=4096)`，user_prompt 为「请整合所有剧情片段，输出完整小说。」。
5. **返回**：`{"final_output": response, "current_phase": "completed"}` → 经 `supervisor_node` 置 `done`，随后触发长期记忆持久化（见 §11.3 / §8.5）。

**输入**：`story_segments` / `user_choices` / `characters` / `world_setting`。
**输出**：`final_output`（完整小说正文）、`current_phase="completed"`。

---

## 7. 状态管理 — `graph/state.py`

`NovelState`（`TypedDict`）是贯穿整个图的全局状态。关键字段（对照源码）：

| 分组 | 字段 |
| --- | --- |
| 用户输入 | `user_request` |
| 世界观 | `world_setting` / `characters` / `rules` / `setting_confirmed` |
| 剧情 | `story_segments` / `current_segment` / `plot_version` / `segment_history` |
| 交互 | `current_options` / `user_choices` / `current_turn` / `awaiting_user` |
| 质控 | `critique` / `critique_score` / `risk_warnings` |
| 输出 | `final_output` |
| 记忆 | `memory`（`MemoryState`） |
| 消息 | `messages`（LangGraph `add_messages` 注解，自动合并） |
| 人工审核 | `human_approval`（`pending` / `approved` / `rejected`） |
| 控制 | `current_phase` / `iteration_count` / `max_internal_iterations` |

`current_phase` 是路由核心，取值流转：`init → world_building → story_progressing → critic_loop → completed → done`。

辅助类型：`OptionItem`（`id` / `text` / `hint` / `risk_level`）、`UserChoice`（`turn_id` / `choice_type` / `content` / `selected_option`）、`SegmentHistoryItem`（`turn` / `segment` / `options`）。

---

## 8. 工具层

### 8.1 记忆工具 `tools/memory.py`

> 源码注释：为 Agent 提供故事记忆能力，记录剧情发展状态、人物性格特点/关系/成长弧线，以及剧情线索和伏笔点，有效避免挖坑不填。

- `MemoryState` 含：角色档案（`CharacterMemory`：性格 / 关系 / 成长弧 / 最近出现轮次）、剧情线索（`PlotThread`：active/resolved/abandoned）、伏笔（`Foreshadowing`：pending/fulfilled）、时间线、世界观笔记。
- `build_memory_context`：注入 Prompt 时启用**滑动窗口裁剪**（角色仅保留最近若干轮出现过的；伏笔仅保留最近若干条待回收；时间线仅展示最近若干条），控制 token 量。
- `apply_updates` / `create_initial_memory`：从新片段中提取并更新记忆；初始记忆由 WorldBuilder 生成的角色创建。

### 8.2 RAG 工具 `tools/rag_tool.py`

> 源码注释：RAG 检索工具——向量检索 + Reranker 重排序；使用 ChromaDB 进行向量存储，SiliconFlow API 进行 Embedding 和 Rerank；先做向量粗召回、再做 Rerank 精排、最后带缓存返回最相关的知识库片段。

- 流程：**向量检索（ChromaDB，候选 `RETRIEVE_K=20`）→ Reranker 重排序（SiliconFlow `bge-reranker`，保留 `RERANK_TOP_K=5`）→ 返回文本**。
- 内置**进程内 TTL 缓存**（`_TTLCache`，默认 300s，容量 128 条 LRU 淘汰）：同样的查询在 TTL 内直接返回上次结果，减少重复 Embedding / Rerank 调用。缓存条目超过 128 条时淘汰最旧数据，防止内存无限增长。
- `retrieve_for_writing(...)`：为写作 Agent 自动拼接 query（用户输入前 100 字 + 世界观关键词前 50 字 + 当前上下文前 50 字）并检索；无结果返回空字符串。
- 依赖 ChromaDB 服务与已入库知识库（见 §13）。
- 实现备注：检索为**同步阻塞**调用（`requests.post`、`vector_store.similarity_search`），在 async 节点中会阻塞事件循环（见 §17）。

### 8.3 搜索工具 `tools/search_tool.py`

> 源码注释：Bing 搜索工具——基于魔搭社区 bing-cn-mcp-enhanced MCP 服务（云端 streamable_http），提供搜索与网页抓取两类能力。

- 通过 `streamable_http` 连接云端 MCP（或本地 `stdio`），由 `configs/.env` 的 `mcp_bing_config` 决定；有配置即 `MCP_BING_ENABLED=True`。
- 提供 `search_bing` / `search_for_world_building`；未配置 MCP 时安全返回空字符串，不影响主流程。
- `_run_async`：在同步环境中运行异步 MCP 协程。当事件循环已在运行（如 LangGraph 节点内）时，会**新建子线程 + 独立事件循环**执行，绕开 "loop already running" 限制。因此在 async 服务中调用会开线程等网络，对事件循环较重。

### 8.4 文档工具 `tools/document_util.py`

> 源码注释：文档加载和分割——用于 RAG 知识库入库；参考 exchange_rag_agent/document_util.py 实现；支持 txt、md、pdf、docx、csv 格式。

- `LOADER_MAP` 按后缀名映射 Loader（`TextLoader` / `PyMuPDFLoader` / `Docx2txtLoader` / `CSVLoader`）；`RecursiveCharacterTextSplitter`（chunk_size=200, overlap=20，分隔符含中文字符 `。，！？` 等）分割。
- `create_index_from_dir()`：将 `knowledge_base/` 下全部文档入库到 ChromaDB，供 RAG 检索。
- `SUPPORTED_FORMATS` = `{".txt", ".md", ".pdf", ".docx", ".csv"}`，被 `server.py` 的上传接口用于格式校验。
- ⚠️ 注意事项：`document_util.py` 的 `__main__` 入口硬编码了 `create_index_from_dir("C:\\Users\\yzx\\Downloads")`（开发者本地路径），直接用 `python -m src.tools.document_util` 会从该目录入库；**建议改用 `create_index_from_dir()` 默认参数（取项目 `knowledge_base/`）或显式传参**。

### 8.5 长期记忆工具 `tools/long_term_memory.py`（续写持久化）

> 源码注释：长期记忆存储——当一个会话创作完成（phase == done）时，将其世界观、角色、规则、前情段落、记忆状态及正文持久化，以便后续「续写」时恢复上下文；与 checkpointer / 会话元数据同库不同表。

- `save_long_term_memory(session_id, state)`：会话 `done` 时，将世界观 / 角色 / 规则 / `story_segments` / `memory`(`memory_state`) / `final_output` / `title` 以 `session_id` 为主键写入 `long_term_memories` 表（`INSERT OR REPLACE`，续写完成后刷新）。
- `get_long_term_memory(memory_id)` / `list_long_term_memories()`：按主键取单条（反序列化 JSON 字段）或列出摘要（preview 取 `final_output` 前 80 字，为空则取最后一段前 80 字），供续写恢复与列表展示。
- 写入由 `server.py` 在会话完成后调用（见 §10 `/resume` 与 `_save_meta`）；读取由续写流程恢复上下文。

---

## 9. 流式输出（SSE）— `src/utils/streaming.py`

> 源码注释：把框架层的、可能含任意对象的异步事件流，安全地映射成前端友好的、带语义类型的 SSE 流，并通过 current_node 追踪和字段白名单让前端既能实时显示 token，又能拿到干净的节点结果。

`server.py` 的 `/api/sessions/{id}/stream` 端点用 `graph.astream_events(Command(resume=action), config, version="v2")` 逐事件推送，经 `transform_graph_events` 转为 SSE：

| 事件类型 | 含义 |
| --- | --- |
| `node_start` | 某节点开始执行（含节点名与 input） |
| `node_end` | 节点完成（仅回传关键状态字段白名单，如 `current_segment`、`current_options`、`world_setting` 等） |
| `token` | LLM token 片段（附 `node` 字段标明来源节点，如 `story_driver` 产出正文） |
| `interrupt` | 图在 `interrupt` 处暂停，等待用户（自定义事件） |
| `error` | 节点执行错误 |
| `final` | 流结束后回传完整状态快照（`SessionResponse`），前端据此一次性渲染选项 / 世界观 |
| `done` | 流结束 |

- `format_sse_event` 通过 `_json_safe()` 递归转换不可序列化对象（如 `Command`、`interrupt` payload），避免 `TypeError`。
- `token` 事件会附带 `current_node`（最近一次 `on_chain_start` 的节点名），前端可据此判断 token 来自哪个节点。

---

## 10. API 接口 — `server.py`

所有响应统一封装为 `SessionResponse`（含 `session_id / phase / turn / segment / options / world_setting / characters / rules / critique / risk_warnings / final_output / human_approval / review / error`）。`phase` 字段对外展示时会做映射：`world_building` / `story_progressing` / `completed` / `done` 原样，其它统一映射为 `"processing"`。

`review` 字段与 `human_approval="pending"` 仅在 `interrupt` 载荷的 `kind` 属于 `REVIEW_KINDS = ("setting_confirm", "setting_review", "segment_review")` 时下发，用于驱动前端弹出审核面板（`kind="choice"` 的选项面板不触发 `review`/`pending`）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/sessions` | 创建会话：接收 `user_request`，`ainvoke` 启动图；遇 `GraphInterrupt` 读取已 checkpoint 状态返回 |
| `POST` | `/api/sessions/{id}/action` | 发送用户操作（非流式）：接收 `{action, payload?}`，用 `Command(resume=...)` 恢复被中断的图 |
| `GET` | `/api/sessions/{id}` | 获取会话当前状态（从 checkpointer 读取，不执行图） |
| `GET` | `/api/sessions` | 列出全部会话元数据（进度摘要） |
| `PATCH` | `/api/sessions/{id}` | 更新会话标题（`UpdateTitleRequest`） |
| `DELETE` | `/api/sessions/{id}` | 删除会话元数据（仅删 `session_metas`，不清理长期记忆与 checkpoint） |
| `GET` | `/api/sessions/{id}/stream?action=...` | **SSE 流式**：逐节点 / 逐 token 推送；用户做出选择后带 `action=用户输入` 调用此接口恢复图 |
| `POST` | `/api/sessions/{id}/resume` | **续写**：基于已完成会话的长期记忆，恢复世界观/角色/规则/记忆，清空前情进度，以 `story_progressing` 阶段新 thread 启动图 |
| `GET` | `/api/memories` | 列出所有长期记忆（续写入口页用） |
| `GET` | `/api/memories/{memory_id}` | 获取单条长期记忆详情（debug/预览用） |
| `POST` | `/api/knowledge/upload` | 上传参考文件（txt/md/pdf/docx/csv）→ 落盘 `knowledge_base/` → 解析分割 → 入库 Chroma（异步线程执行，不阻塞） |
| `GET` | `/api/knowledge/files` | 列出知识库目录中已上传的参考文件 |

**请求模型：**

- `CreateSessionRequest { user_request: str }`
- `ActionRequest { action: str, payload?: str }`（`payload` 优先级高于 `action`）
- `UpdateTitleRequest { title: str }`

> 实现要点：
> - `GraphInterrupt` 来自 `langgraph.errors`；`_run_graph` 在 `ainvoke` 抛出 `GraphInterrupt` 时读取 `aget_state` 返回已 checkpoint 的状态快照。
> - 文本类上传文件会经 `_normalize_text_bytes()` 做编码规范化（先按 UTF-8 试解码，失败再按 GBK 解码后重编码为 UTF-8），避免中文 Windows 下 GBK 文件被 `TextLoader`(UTF-8) 解析失败。
> - `stream_session` 在流结束后补发 `interrupt` 事件（若停在人工审核）再发 `final` 快照，保证前端能拿到审核面板与完整状态。
> - 端口为 **8001**（非旧文档中提到的 8000），与前端 `vite.config.js` 的 proxy 目标一致。

---

## 11. 数据库与持久化

所有持久化（LangGraph checkpointer、会话元数据、长期记忆）**共用同一份 SQLite 文件**——项目根目录下的 `novel.db`。`src/utils/database.py` 统一定义 `DB_PATH = novel.db` 与 `get_conn()`（启用外键、`sqlite3.Row` 行工厂），`_init_tables` 在业务表 `session_metas` 与 `long_term_memories` 不存在时创建它们；LangGraph 自管的 checkpointer 表由框架自行维护。

### 11.1 Checkpointer（断点续跑）

由 `src/graph/workflow.py` 的 `build_graph_async()` 构建：

```python
conn = await aiosqlite.connect(get_db_path())
checkpointer = AsyncSqliteSaver(conn)
workflow = _build_workflow()
return workflow.compile(checkpointer=checkpointer)
```

> 注意：`AsyncSqliteSaver` 需手动持有连接（`aiosqlite.connect` 返回的实例），使其在应用生命周期内保持存活；`compile()` 直接接收 `AsyncSqliteSaver(conn)` 而非上下文管理器，否则会报 `Invalid checkpointer` 错误。当前**仅实现 SQLite 后端**，未提供 PostgreSQL 分支（尽管依赖中声明了 `langgraph-checkpoint-postgres`）。

### 11.2 会话元数据 `utils/session_store.py`

复用同一 `novel.db` 的 `session_metas` 表（非独立库），存储会话标题 / 阶段 / 轮次 / 片段数 / 预览，供列表页与进度展示使用。提供 `save_session_meta`（`INSERT OR REPLACE`，保留 `created_at`）/`get_session_meta`/`list_session_metas`（按 `updated_at` 倒序）/`update_session_meta`/`delete_session_meta`。

- 实现备注：该模块为**同步阻塞**（`sqlite3` 标准库），在 async 协程中调用会阻塞事件循环。

### 11.3 长期记忆 `tools/long_term_memory.py`

复用同一 `novel.db` 的 `long_term_memories` 表（见 §8.5），供已完成会话续写时恢复上下文。由 `server.py` 的 `_save_meta` 在 `current_phase == "done"` 时调用 `save_long_term_memory`。

### 11.4 生命周期 `lifespan`（`server.py`）

- 启动时：`app_graph_async = await build_graph_async()`。
- 关闭时：关闭异步 checkpointer 连接（`await cp.conn.close()` 处理 aiosqlite 异步连接）。

---

## 12. 前端结构详解 — `frontend/src`

前端基于 **Vue 3 + Element Plus + Axios + Three.js**，通过 `EventSource` 消费后端 SSE 流。

### 12.1 入口与构建

- `index.html`：HTML 模板，`main.js` 挂载 `App.vue`。
- `vite.config.js`：dev 端口 **5173**，开发期将 `/api` 代理到 `http://localhost:8001`（注意与后端端口一致）；`build.outDir = dist`。
- `main.js`：引入 Vue、Element Plus 及样式。

### 12.2 API 封装 — `api/client.js`

基于 axios 封装，`baseURL: '/api'`。导出函数与后端一一对应：

`createSession` / `sendAction` / `getSession` / `listSessions` / `updateSession` / `deleteSession` / `resumeSession` / `streamAction`（返回 `EventSource`）/ `listMemories` / `getMemory` / `uploadKnowledgeFile` / `listKnowledgeFiles`。

- §10 中多个长耗时接口（创建会话、发送操作、续写、上传）在客户端把超时放宽到 **5 分钟**（AI 生成世界观/剧情耗时较长）。

### 12.3 主应用 — `App.vue`

约 1850 行，承担全部交互逻辑，关键状态与方法：

- 会话流程：`currentPhase`、`initialRequest`、`sessionId`、`messages`、`options`、`worldSetting`、`finalOutput`。
- 流式渲染：`streamingMsgIndex` / `streamingTarget` / `typeWriter(index, fullText)` 实现打字机效果；`runStream(action, displayText)` 打开 `EventSource` 并逐事件（`node_start`/`token`/`node_end`/`interrupt`/`final`/`done`）更新 UI；`finishStream` / `applyFinal` / `applyResponse` 收尾。
- 人工审核面板：`REVIEW_KINDS = ['setting_confirm','setting_review','segment_review']`；`isReviewPending` 计算属性；`review` 载荷驱动弹窗，`sendApproval(decision)` 将批准/驳回结果作为下一轮 `action` 经 SSE 流回传。
- 风险标注：`riskLabel(level)` / `riskClass(level)` 用于选项风险等级着色。
- 会话管理：`loadSessions` / `onSelectSession` / `onCreate` / `onRename` / `onDelete` / `onResume`（续写）/ `resetWorkspace`。
- 回溯：`backtrack()`（发送「回到上一步」）。
- 知识库：`triggerUpload` / `onFileSelected` / `uploading` / `loadKnowledgeFiles` / `knowledgeFiles` / `formatSize`。

### 12.4 组件 — `components/`

- `SessionSidebar.vue`：会话侧边栏，提供新建、选择、重命名、删除、续写入口。
- `PaperScene.vue`：Three.js 3D 纸张场景（可视化氛围元素）。
- `Button3D.vue`：Three.js 3D 按钮组件。

### 12.5 样式 — `styles/main.css`

全局样式与主题。

---

## 13. 知识库入库（RAG）

```bash
# 将文档放入 knowledge_base/ 后执行（注意 __main__ 硬编码了本地 Downloads 路径，建议显式传参）：
python -c "from src.tools.document_util import create_index_from_dir; create_index_from_dir()"
```

该脚本会遍历目录、加载支持的文档、分割并写入 ChromaDB 指定 collection，供 `rag_tool.retrieve_for_writing` 在剧情生成时检索参考素材（见 §8.4）。

也可通过前端/接口上传单文件：`POST /api/knowledge/upload`（支持 txt/md/pdf/docx/csv），后端会自动解析分割并入库（见 §10）。

---

## 14. 测试

`tests/` 目录包含：

- `test_agents_fixes.py`：针对 Agent 修复逻辑（如解析路由、质控回滚、回溯边界）的用例。
- `test_server_routes.py`：针对 `server.py` 路由（会话创建/操作/获取/列表等）的用例。

运行：

```bash
pytest                 # 按 pyproject.toml 配置，testpaths=tests，pythonpath=.
# 或
python -m pytest tests/
```

---

## 15. 运行

```bash
# 后端（默认 0.0.0.0:8001）
python server.py
# 或
uvicorn server:app --host 0.0.0.0 --port 8001

# 前端（另开终端）
cd frontend && npm run dev
```

打开前端地址（`http://localhost:5173`）即可开始创作；若已 `npm run build`，后端会直接托管 `frontend/dist`。

> **命令行模式**：旧文档提到 `src/app.py` 提供纯终端交互入口，但**当前代码库中不存在该文件**，暂无命令行入口；如需无界面体验请使用上述 Web 流程或在此基础自行扩展。

---

## 16. 常见问题

- **`TypeError: Object of type Command is not JSON serializable`**：旧版 `streaming.py` 未处理不可序列化对象，现已通过 `_json_safe()` 修复。
- **`Invalid checkpointer ... Received _AsyncGeneratorContextManager`**：异步构建时误将 `AsyncSqliteSaver.from_conn_string()` 直接传给 `compile()`。应改为手动 `aiosqlite.connect` 后 `AsyncSqliteSaver(conn)`（见 §11.1）。
- **`GraphInterrupt` 导入报错**：在 langgraph 1.x 中应 `from langgraph.errors import GraphInterrupt`，而非 `langgraph.types`。
- **RAG 检索为空**：确认 ChromaDB 已启动且知识库已通过 §13 入库。
- **Bing 搜索不生效**：检查 `mcp_bing_config` 格式与网络可达性；未配置时系统会安全跳过搜索。
- **前端连不上后端 / 一直 loading**：确认后端运行在 **8001**，且前端 `vite.config.js` 的 proxy `target` 为 `http://localhost:8001`；SSE 长连接受超时影响，长耗时操作请耐心等待（客户端已放宽到 5 分钟）。
- **上传 txt/md 后解析报编码错误**：已由 `_normalize_text_bytes` 做 UTF-8/GBK 兼容处理；若仍失败，请确认文件非损坏文件。
- **找不到 `.env`**：`.env` 位于 **`configs/` 目录**下（与 `settings.yaml` 同级），是项目唯一的环境变量来源；`configs/settings.yaml` 仅作默认值后备。
- **只有一个数据库文件 `novel.db`**：checkpointer、会话元数据（`session_metas`）、长期记忆（`long_term_memories`）同库不同表，不区分多个 SQLite 文件，也未使用 PostgreSQL。
- **`src/graph/edges.py` / `nodes.py` / `src/app.py` / `docs/supervisor_说明.md` 不存在**：这些为旧文档遗留描述，实际边/节点逻辑集中在 `workflow.py` 与 `supervisor.py`；命令行入口与 supervisor 独立文档当前均缺失。

---

## 17. 已知限制与技术债

以下内容基于 `docs/项目经验总结.md` 与源码核查，供后续优化参考：

1. **同步阻塞混入异步服务**：`rag_tool.py`（`requests.post` / `vector_store.similarity_search`）、`session_store.py`（`sqlite3` 标准库）等同步调用被直接用在 async 节点中，会阻塞事件循环。多会话并发时，单个会话的同步阻塞会拖慢其它会话。优化方向：Embedding/Rerank 改用 `httpx.AsyncClient`，数据库操作统一换 `aiosqlite`，并优化 `search_tool._run_async` 开线程方案。

2. **单文件 SQLite 的取舍**：checkpointer、会话元数据、长期记忆全在同一 `novel.db`。优点是部署简单、零额外服务；隐患是生产环境单文件是瓶颈，checkpointer 的高频写会拖慢元数据读取。好消息是 checkpointer 由 LangGraph 自管、耦合度低，未来可单独拆库（PostgreSQL 分支）。

3. **知识库入库入口硬编码**：`document_util.py` 的 `__main__` 写死了 `C:\Users\yzx\Downloads`，不建议直接用 `python -m src.tools.document_util`，应显式调用 `create_index_from_dir()` 或传参。

4. **端口约定**：后端固定 **8001**（非常见 8000），前后端须保持一致；文档旧版曾误写为 8000。

5. **审核面板与 `human_approval` 语义**：`interrupt` 的 `kind` 决定前端是否弹出审核面板——仅 `REVIEW_KINDS` 三类（`setting_confirm`/`setting_review`/`segment_review`）会置 `human_approval="pending"` 并下发 `review`；选项面板 `kind="choice"` 不触发该机制。理解数据流时需注意区分。

6. **文档待补**：`supervisor` 的详细设计说明（旧文档引用的 `docs/supervisor_说明.md`）与命令行入口（`src/app.py`）当前均缺失，建议后续补充或从源码注释整理。

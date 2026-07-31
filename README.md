# 交互式多 Agent 协作小说创作系统

一个基于 **LangGraph** 编排、**FastAPI** 提供 REST/SSE 接口、**Vue 3** 提供前端的交互式小说创作系统。系统由多个专职 Agent 协作完成「世界观构建 → 剧情生成 → 内部质控 → 人工审核 → 全文整合」的完整创作闭环，并通过 LLM 流式输出与服务器推送事件（SSE）实现逐 token 的前端实时渲染。

---

## 1. 项目简介

用户只需输入一句创作需求（例如「写一篇赛博朋克背景下的侦探小说」），系统便会：

1. 自动检索资料、生成世界观设定、角色与规则；
2. 逐段推进剧情，每轮给出多个分支选项供用户选择或自由输入；
3. 内置 Critic Agent 对设定与每段剧情做一致性 / 合规 / 风险审查，低分时中断交由人工确认；
4. 用户可随时回溯、要求重来或生成全文；
5. 最终由 Integrator Agent 将全部片段润色整合为完整小说。

整个流程由 LangGraph 的有状态图（`StateGraph`）驱动，支持断点续跑（checkpoint）与 Human-in-the-Loop（`interrupt`）。

---

## 2. 系统架构

### 2.1 整体数据流

```
                 ┌─────────────────────────────────────────┐
  用户输入 ─────▶ │              FastAPI (server.py)          │
                 │  /api/sessions  · /action · /stream(SSE)  │
                 └───────────────┬───────────────────────────┘
                                 │  graph.ainvoke / astream_events
                                 ▼
                 ┌─────────────────────────────────────────┐
                 │      LangGraph Workflow (StateGraph)      │
                 │                                           │
                 │   supervisor ──▶ world_builder ──▶ critic │
                 │       │                ▲            │      │
                 │       │                │            ▼      │
                 │       └──▶ story_driver ──▶ critic ◀┘      │
                 │                 │                  │        │
                 │                 ▼                  ▼        │
                 │            (interrupt 等待用户)    supervisor│
                 │                                  │          │
                 │                            integrator ─▶ END │
                 └───────────────────────────────────────────┘
                                 │
            ┌────────────────────┼─────────────────────┐
            ▼                    ▼                      ▼
      Checkpointer(SQLite/    Memory 工具         RAG 工具 (ChromaDB)
      Postgres, 断点续跑)   搜索工具 (Bing MCP)   搜索引擎 (SiliconFlow)
```

### 2.2 图节点与路由（`src/graph/workflow.py`）

| 节点 | 来源 | 职责 |
|------|------|------|
| `supervisor` | `agents/supervisor.py` | 调度中心：解析用户输入、路由、在等待用户输入时调用 `interrupt` 暂停图 |
| `world_builder` | `agents/researcher.py` | 调用 Bing 搜索 + LLM 生成世界观设定 / 角色 / 规则 |
| `story_driver` | `agents/writer.py` | 根据历史、记忆、RAG 检索生成下一段剧情与分支选项 |
| `critic` | `agents/reviewer.py` | 内部质控：审查设定或剧情片段，低分时 `interrupt` 人工审核 |
| `integrator` | `agents/integrator.py` | 拼接所有片段并润色输出完整小说 |

**条件边路由：**
- `supervisor_route`（`supervisor.py` 末尾）：依据 `current_phase` 决定下一个节点。
  - `init` → `world_builder`
  - `world_building`（已生成设定）→ `supervisor`（确认）或 `story_driver`
  - `story_progressing` + `awaiting_user` → `supervisor`（在 interrupt 处暂停）
  - `critic_loop` → `critic` 或打回 `story_driver`
  - `completed` → `integrator`
  - `done` → `END`
- `critic_route`（`supervisor.py` 末尾）：审查通过后进入剧情推进，未通过与人工驳回则打回对应生成节点。

> 注：`src/graph/edges.py` 与 `src/graph/nodes.py` 当前为占位文件（`TODO`），实际边与节点注册逻辑集中在 `workflow.py` 与 `supervisor.py` 中。

---

## 3. 目录结构

```
.
├── server.py                 # FastAPI 入口：API 路由、生命周期、SSE 流式
├── src/app.py                # CLI 入口：终端交互式创作（无需前端）
├── config.py                 # 根配置占位文件（实际配置见 src/utils/config.py，见 §5）
├── configs/
│   ├── settings.yaml         # YAML 默认配置（LLM / 创作 / 质控 / RAG / misc）
│   └── .env                  # 环境变量（优先级最高，实际存放于项目根目录 .env）
├── pyproject.toml            # 依赖清单
├── exchange_rag_agent/       # RAG 参考实现（独立模块，供 src/tools 下的 RAG 代码参考）
│   ├── chroma_util.py        # ChromaDB 连接与集合管理
│   ├── document_util.py      # 文档加载 / 分割 / 入库
│   ├── rag_agent.py          # RAG Agent 封装
│   └── rag_tool.py           # 检索工具实现
├── tools/                    # 根级工具镜像（历史遗留，主逻辑以 src/tools 为准）
│   └── memory.py
├── utils/                    # 根级工具镜像（历史遗留，主逻辑以 src/utils 为准）
│   └── llm.py
├── src/
│   ├── agents/               # 五个专职 Agent
│   │   ├── supervisor.py     # 调度中心 + 两条条件路由
│   │   ├── researcher.py     # world_builder_node（世界观构建）
│   │   ├── writer.py         # story_driver_node（剧情推进）
│   │   ├── reviewer.py       # critic_node（内部质控）
│   │   └── integrator.py     # integrator_node（全文整合）
│   ├── graph/
│   │   ├── state.py          # NovelState 全局状态定义
│   │   ├── workflow.py       # 图构建（同步 / 异步）
│   │   ├── edges.py          # 边定义占位（TODO）
│   │   └── nodes.py          # 节点注册占位（TODO）
│   ├── prompts/              # 各 Agent 的提示词模板
│   ├── tools/                # 工具层（实际生效）
│   │   ├── memory.py         # 故事记忆（角色 / 线索 / 伏笔 / 时间线）
│   │   ├── rag_tool.py       # 向量检索 + Reranker
│   │   ├── search_tool.py    # Bing 搜索（MCP）
│   │   └── document_util.py  # 文档加载 / 分割 / 入库
│   └── utils/
│       ├── config.py         # 配置读取（.env > YAML）
│       ├── llm.py            # LLM 调用封装（ChatOpenAI，流式）
│       ├── streaming.py      # astream_events → SSE 事件转换
│       ├── database.py       # checkpointer 选择（SQLite / Postgres）
│       ├── session_store.py  # 会话元数据（SQLite）
│       └── logger.py         # 日志（控制台 + 轮转文件）
├── frontend/                 # Vue 3 + Element Plus + Vite 前端
│   ├── src/                  # 前端源码（api / components / styles / App.vue / main.js）
│   └── dist/                 # 生产构建产物（server.py 会挂载此目录）
├── knowledge_base/           # RAG 知识库文档目录（需自行准备）
└── tests/                    # 测试（test_agents / test_api / test_graph / test_tools /
                               #        test_long_term_memory / test_session_store）
```

---

## 4. 安装与环境配置

### 4.1 后端

```bash
# 建议使用 Python 3.11+
pip install -e .        # 依据 pyproject.toml 安装全部依赖
# 或：pip install -r requirements.txt（如存在）

# 配置环境变量：项目根目录的 .env（若不存在则手动创建，见 §5.2）
# 注意：.env 实际位于项目根目录，而非 configs/ 子目录
```

核心依赖（节选自 `pyproject.toml`）：`langgraph`、`langgraph-checkpoint-sqlite`、`langgraph-checkpoint-postgres`、`openai`、`fastapi`、`uvicorn`、`sse-starlette`、`langchain-*`、`mcp`、`asyncpg`、`pymupdf`、`docx2txt`。

> 没有 `requirements.txt` 时，直接 `pip install -e .` 即可，依赖全部声明在 `pyproject.toml`。

### 4.2 前端

```bash
cd frontend
npm install
npm run dev      # 开发模式，默认 http://localhost:5173
# 或 npm run build && npm run preview  # 生产构建
```

生产模式下 `server.py` 会尝试挂载 `frontend/dist` 作为静态文件（见 `server.py` 中 `StaticFiles` 挂载，失败则静默跳过，走开发模式）。

### 4.3 可选服务

- **ChromaDB**（RAG 检索）：默认 `localhost:8081`。需自行部署 Chroma 服务。
- **Bing MCP 搜索**：通过 `configs/.env` 中的 `mcp_bing_config` 配置（见 §5）。

---

## 5. 配置说明

配置优先级：**项目根目录 `.env` 环境变量 > `configs/settings.yaml` > 代码默认值**。`src/utils/config.py` 会同时 `load_dotenv()` 根目录 `.env` 与 `configs/.env`（若两者都存在，根目录优先）。读取逻辑见 `src/utils/config.py`。

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

### 5.2 项目根目录 `.env`（覆盖优先级最高）

> `.env` 实际存放在**项目根目录**（与 `server.py` 同级），不是 `configs/` 下。`src/utils/config.py`、`src/tools/*` 等模块都会 `load_dotenv()` 加载它。

```env
# LLM（OpenAI 兼容，示例使用 SiliconFlow）
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash

# 数据库：设置 DATABASE_URL 则使用 PostgreSQL，否则 SQLite
DATABASE_URL=

# RAG / Embedding
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3
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

---

## 6. Agent 详解

### 6.1 Supervisor（调度中心）— `agents/supervisor.py`
- `parse_user_input`：将用户输入解析为动作（`select_option` / `free_input` / `backtrack` / `generate_full` / `confirm_setting` 等）。规则匹配优先（如「继续」「不行」「确认」），兜底走 LLM 解析。
- `handle_backtrack`：处理「回到上一步」，从 `segment_history` 弹出最近一段并恢复状态，受 `MAX_BACKTRACK_STEPS` 限制。
- `supervisor_node`：根据 `current_phase` 推进流程；在 `story_progressing` 且 `awaiting_user` 时调用 `interrupt(...)` 暂停整个图，等待前端通过 `Command(resume=...)` 恢复。
- `supervisor_route` / `critic_route`：两条条件边路由函数（见 §2.2）。

### 6.2 World Builder（世界观构建）— `agents/researcher.py`
- `world_builder_node`：先用 `search_for_world_building` 调 Bing 收集背景资料，再调用 LLM 生成 `world_setting / characters / rules`（JSON 输出），状态进入 `world_building`。

### 6.3 Story Driver（剧情推进）— `agents/writer.py`
- `story_driver_node`：每轮
  1. 汇总近 3 段剧情、`memory` 记忆上下文、`rag_tool.retrieve_for_writing` 检索素材；
  2. 调用 LLM 生成 `segment`（剧情片段）+ `options`（分支选项）+ `memory_updates`；
  3. 选项自动补唯一 `id`（A/B/C…）；
  4. 写入 `story_segments`、`segment_history`（用于回溯）、`memory`；
  5. 状态置 `awaiting_user=True`，等待用户选择。

### 6.4 Critic（内部质控）— `agents/reviewer.py`
- `critic_node`：根据是否存在 `current_segment` 区分「设定审查」或「剧情片段审查」。
- 阈值随迭代次数递减：`effective_threshold = max(PASS_THRESHOLD - iteration_count, 4)`。
- 评分低于阈值且未达最大迭代 → 调用 `interrupt` 抛出人工审核面板（批准 / 驳回）。驳回则进入 `critic_loop` 打回重生成；达到最大迭代次数则跳过中断直接放行。
- 结果写入 `critique / critique_score / risk_warnings`。

### 6.5 Integrator（全文整合）— `agents/integrator.py`
- `integrator_node`：将 `story_segments`、角色、用户选择汇总，调用 LLM 润色输出 `final_output`，状态进入 `completed` → `done`。

---

## 7. 状态管理 — `graph/state.py`

`NovelState`（`TypedDict`）是贯穿整个图的全局状态，关键字段：

| 分组 | 字段 |
|------|------|
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

`current_phase` 是路由核心，取值：`init → world_building → story_progressing → critic_loop → completed → done`。

---

## 8. 工具层

### 8.1 记忆工具 `tools/memory.py`
为 Agent 提供长期故事记忆，结构 `MemoryState` 含：角色档案（`CharacterMemory`，含性格 / 关系 / 成长弧 / 最近出现轮次）、剧情线索（`PlotThread`，active/resolved/abandoned）、伏笔（`Foreshadowing`，pending/fulfilled）、时间线、世界观笔记。
- `build_memory_context`：注入 Prompt 时启用**滑动窗口裁剪**（角色仅保留最近 5 轮、伏笔仅保留最近 10 条），控制 token 量。
- `extract_memory_updates` / `_apply_updates`：从新片段中提取并更新记忆。

### 8.2 RAG 工具 `tools/rag_tool.py`
- 流程：**向量检索（ChromaDB，候选 `RETRIEVE_K=20`）→ Reranker 重排序（SiliconFlow `bge-reranker`，保留 `RERANK_TOP_K=5`）→ 返回文本**。
- 内置**进程内 TTL 缓存**（`_TTLCache`，默认 300s），减少重复 Embedding / Rerank 调用。
- `retrieve_for_writing(...)`：为写作 Agent 自动拼接 query（用户输入 + 世界观关键词 + 当前上下文）并检索。
- 依赖 ChromaDB 服务与已入库知识库（见 §12）。

### 8.3 搜索工具 `tools/search_tool.py`
- 基于 **Bing MCP 服务**（`bing-cn-mcp-enhanced`），支持 `streamable_http`（云端）与 `stdio`（本地 npx）两种连接方式，由 `mcp_bing_config` 决定。
- 提供 `search_bing` / `fetch_webpage` / `search_for_world_building`。未配置 MCP 时安全返回空字符串。

### 8.4 文档工具 `tools/document_util.py`
- 支持 `txt / md / pdf / docx / csv` 加载（`LOADER_MAP`），用 `RecursiveCharacterTextSplitter`（chunk_size=200, overlap=20）分割。
- `create_index_from_dir()`：将 `knowledge_base/` 下全部文档入库到 ChromaDB，供 RAG 检索。

---

## 9. 流式输出（SSE）— `utils/streaming.py`

`server.py` 的 `/api/sessions/{id}/stream` 端点用 `graph.astream_events(Command(resume=action), config, version="v2")` 逐事件推送，经 `transform_graph_events` 转为 SSE：

| 事件类型 | 含义 |
|----------|------|
| `node_start` | 某节点开始执行（含节点名与 input） |
| `node_end` | 节点完成（仅回传关键状态字段，如 `current_segment`、`current_options`） |
| `token` | LLM token 片段（附 `node` 字段标明来源节点，如 `story_driver` 产出正文） |
| `interrupt` | 图在 `interrupt` 处暂停，等待用户 |
| `error` | 节点执行错误 |
| `final` | 流结束后回传完整状态快照（`SessionResponse`），前端据此一次性渲染选项 / 世界观 |
| `done` | 流结束 |

- `format_sse_event` 通过 `_json_safe()` 递归转换不可序列化对象（如 `Command`、`interrupt` payload），避免 `TypeError`。

---

## 10. API 接口 — `server.py`

所有响应统一封装为 `SessionResponse`（含 `session_id / phase / turn / segment / options / world_setting / characters / rules / critique / risk_warnings / final_output / human_approval / error`）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/sessions` | 创建会话：接收 `user_request`，`ainvoke` 启动图；遇 `GraphInterrupt` 读取已 checkpoint 状态返回 |
| `POST` | `/api/sessions/{id}/action` | 发送用户操作：`ainvoke(Command(resume=action))` 恢复被中断的图 |
| `GET` | `/api/sessions/{id}` | 获取会话当前状态 |
| `GET` | `/api/sessions` | 列出全部会话元数据（进度摘要） |
| `PATCH` | `/api/sessions/{id}` | 更新会话标题（`UpdateTitleRequest`） |
| `DELETE` | `/api/sessions/{id}` | 删除会话元数据 |
| `GET` | `/api/sessions/{id}/stream?action=...` | **SSE 流式**：逐节点 / 逐 token 推送，用户做出选择后调用此接口恢复图 |

> `GraphInterrupt` 来自 `langgraph.errors`（`server.py` 已正确导入）。

---

## 11. 数据库与持久化

### 11.1 Checkpointer（断点续跑）
由 `src/utils/database.py` 管理：
- 设置 `DATABASE_URL` → 使用 `PostgresSaver`；否则 → `SqliteSaver`（文件 `novel_sessions.db`）。
- `src/graph/workflow.py` 提供两个构建函数：
  - `build_graph()`：同步图（使用 `get_checkpointer()`）。
  - `build_graph_async()`：异步图（SQLite 用 `AsyncSqliteSaver(aiosqlite.connect(...))`，Postgres 用 `AsyncPostgresSaver`）。**注意 `from_conn_string()` 返回的是异步上下文管理器，必须手动持有连接实例**，否则 `compile()` 会报 `Invalid checkpointer` 错误。

### 11.2 会话元数据 `utils/session_store.py`
独立的 SQLite 库（`novel_sessions_meta.db`），存储会话标题 / 阶段 / 轮次 / 片段数 / 预览，供列表页与进度展示使用，与 checkpointer 库分离。

### 11.3 生命周期 `lifespan`（`server.py`）
- 启动时：`app_graph_async = await build_graph_async()`。
- 关闭时：依次关闭同步 / 异步 checkpointer 连接（`await cp.conn.close()` 处理 aiosqlite 异步连接）。

---

## 12. 知识库入库（RAG）

```bash
# 将文档放入 knowledge_base/ 后执行：
python -m src.tools.document_util
```
该脚本会遍历目录、加载支持的文档、分割并写入 ChromaDB 指定 collection，供 `rag_tool.retrieve_for_writing` 在剧情生成时检索参考素材。

---

## 13. 运行

```bash
# 后端（默认 0.0.0.0:8000）
python server.py
# 或
uvicorn server:app --host 0.0.0.0 --port 8000

# 前端（另开终端）
cd frontend && npm run dev
```

打开前端地址即可开始创作；若已 `npm run build`，后端会直接托管 `frontend/dist`。

### 13.5 命令行模式（无需前端）

`src/app.py` 提供纯终端交互入口，适合无界面环境快速体验：

```bash
python -m src.app
```

启动后按提示输入创作需求，随后每轮根据 `current_phase`（剧情推进 / 世界观构建 / 已完成）在终端输入选项（A/B/C 或自由文本）或「生成全文」「结束」即可。底层复用 `build_graph()` 同步图与 `Command(resume=...)` 恢复机制。

---

## 14. 常见问题

- **`TypeError: Object of type Command is not JSON serializable`**：旧版 `streaming.py` 未处理不可序列化对象，现已通过 `_json_safe()` 修复。
- **`Invalid checkpointer ... Received _AsyncGeneratorContextManager`**：异步构建时误将 `AsyncSqliteSaver.from_conn_string()` 直接传给 `compile()`。应改为手动 `aiosqlite.connect` 后 `AsyncSqliteSaver(conn)`（见 §11.1）。
- **`GraphInterrupt` 导入报错**：在 langgraph 1.x 中应 `from langgraph.errors import GraphInterrupt`，而非 `langgraph.types`。
- **RAG 检索为空**：确认 ChromaDB 已启动且知识库已通过 §12 入库。
- **Bing 搜索不生效**：检查 `mcp_bing_config` 格式与网络可达性；未配置时系统会安全跳过搜索。
- **找不到 `configs/.env`**：`.env` 实际位于**项目根目录**（与 `server.py` 同级）。`configs/settings.yaml` 仅作默认值后备。
- **根目录 `config.py` 是空的**：它是历史占位文件，真正生效的配置在 `src/utils/config.py`，请勿依赖根目录 `config.py`。
- **`tools/` 与 `utils/` 根目录文件**：这是历史遗留的镜像目录，主逻辑以 `src/tools/`、`src/utils/` 为准，避免误改。
- **`exchange_rag_agent/` 目录**：是 RAG 能力的参考实现（独立模块），`src/tools/rag_tool.py` 与 `document_util.py` 的设计参考了它，但运行时以 `src/tools` 下代码为准。

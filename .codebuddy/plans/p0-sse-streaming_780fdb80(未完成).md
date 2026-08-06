---
name: p0-sse-streaming
overview: 实现 SSE 流式接口，让 LLM token 实时推送到前端（打字机效果），消除整轮阻塞等待，将"首字出现时间"从整轮执行完成后降至数百毫秒。
todos:
  - id: update-llm-client
    content: 将 `src/utils/llm.py` 的 OpenAI 原生客户端替换为 LangChain ChatOpenAI，保持 `llm_call` 接口不变，新增流式函数
    status: pending
  - id: fix-stream-endpoint
    content: 修复 `server.py` 的 `/stream` SSE 端点，接受 `action` 查询参数传入用户输入，始终初始化异步图
    status: pending
    dependencies:
      - update-llm-client
  - id: add-sse-stream-client
    content: 在 `frontend/src/api/client.js` 中添加 SSE 流式操作函数 `streamAction(sessionId, action)`
    status: pending
  - id: switch-frontend-to-sse
    content: 重写 `frontend/src/App.vue` 的 `sendUserInput` 方法，改用 EventSource 连接 SSE，实现逐节点/逐 token 实时渲染
    status: pending
    dependencies:
      - add-sse-stream-client
      - fixed-stream-endpoint
---

## 需求

执行 P0 优化方案：实现 SSE 流式输出，让用户在点击选项后立即看到文本逐段出现，消除"整轮阻塞等待"的体验。

### 核心目标
- 放弃 `/action` 阻塞接口，前端改用 SSE 连接 `/stream`
- 后端用 `astream_events` 逐节点/逐 token 推送事件
- 配合 `node_start`/`node_end`/`token` 事件实现实时进度反馈
- 替换 OpenAI 原生客户端为 LangChain ChatOpenAI（兼容 LangGraph 事件追踪）
- 保留所有现有业务逻辑不变

### 非目标（本阶段不做）
- 减少 LLM 调用次数（P1 内容）、RAG 缓存（P2 内容）、模型降级（P3 内容）

### 预期效果
- 当前：用户点击选项 → 等整轮（3+次 LLM + 联网检索）完 → 一次性展示
- 优化后：用户点击选项 → 首字 1-2 秒内出现（writer LLM 开始输出即可见）→ 逐节点实时反馈 → 完成后展示选项


## 技术方案

### 核心思路
将 `src/utils/llm.py` 中的 OpenAI 原生客户端替换为 `langchain_openai.ChatOpenAI`，使 LLM 调用成为 LangChain Runnable，LangGraph 的 `astream_events` 借此能追踪并发出 `on_chat_model_stream`/`on_chain_start`/`on_chain_end` 事件。前端改为 EventSource 连接到 `/stream` 端点，实时消费这些 SSE 事件。

### 架构设计

```mermaid
flowchart TD
    subgraph 前端
        A[用户点击选项] --> B[建立EventSource连接\n/api/sessions/{id}/stream?action=...]
        B --> C{SSE 事件处理}
        C --> D[token事件: 累加到当前消息]
        C --> E[node_start: 显示进度]
        C --> F[node_end: 更新状态/选项]
        C --> G[interrupt: 展示选项]
        C --> H[done: 关闭连接]
    end

    subgraph 后端
        I[GET /stream?action=X] --> J[app_graph.astream_events\nCommand(resume=X)]
        J --> K[transform_graph_events]
        K --> L[推 SSE 事件]
    end
```

### 关键技术决策

1. **为什么用 LangChain ChatOpenAI 而非直接 OpenAI 客户端？**
   - LangGraph 的 `astream_events` 只追踪 LangChain Runnable 的调用链
   - 原生 OpenAI 客户端不产生 `on_chat_model_stream` 事件
   - `langchain_openai` 依赖已存在 `pyproject.toml` 中，无需新增依赖

2. **`llm_call` 接口不变化**
   - 保持返回 `str`，内部从 `chat.invoke(messages)` 获取 `.content`
   - 所有 Agent 节点的代码无需改动
   - 新增 `llm_stream()` 函数用于流式场景

3. **SSE 端点复用现有 `/stream` 路由**
   - 当前已有 `/api/sessions/{id}/stream` 实现但不接收用户输入
   - 改为接收 `action` 查询参数，传入 `Command(resume=action)`
   - 利用现有的 `transform_graph_events` 进行事件转 SSE

4. **前端保留 `createSession` 为 POST**
   - 首次创建会话（world_building）保持同步，因为涉及搜索、长文本生成
   - 后续用户交互轮次全部切换 SSE

5. **JSON 输出处理**
   - writer 提示词要求输出 JSON（含 `segment` 和 `options`）
   - token 事件给出的是 JSON 片段，前端缓冲等待 `node_end` 事件拿到解析后的 `current_segment`
   - 同时 `node_start` 事件提供"节点正在运行"的即时反馈

### 实施要点
- `server.py` 的 lifespan 中始终初始化异步图（不仅是 Postgres 场景）
- SSE 端点增加 `action` 查询参数，URL 格式：`/api/sessions/{id}/stream?action=A`
- 前端 EventSource 不支持 POST 传参，所以用 GET+query 传递用户输入
- 保留 POST /action 作为兼容兜底（前端不用但接口不断）

### 实现笔记
- **性能**: 流式的核心收益是"体感延迟"，首字出现时间从"整轮完成"缩短到"writer 开始输出"（约 1-2 秒）。后端实际 LLM 调用次数不变，但用户无需等待 critic/memory 完成即可看到文本。
- **熔断降级**: SSE 连接断开时，触发 `finally` 块中的 `done` 事件，前端可提示"连接中断"并允许重试。
- **Blast radius**: 只改动 `llm.py`（替换客户端）、`server.py`（改 stream 端点）、`App.vue`（切换 SSE 调用）。所有 Agent 节点和业务逻辑不变。


## 扩展使用

### SubAgent
- **code-explorer**: 在实施阶段协助搜索多文件改动点和验证导入路径，确保 `langchain_openai.ChatOpenAI` 替换后所有引用正确。

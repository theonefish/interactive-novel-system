---
name: p1-p2-optimization
overview: P1（减少 LLM 调用次数）+ P2（RAG 缓存与基础优化），共 7 项改动，不含日志系统
todos:
  - id: p1-merge-story-memory
    content: 合并 story_driver 剧情+记忆为 1 次 LLM：改 writer_prompt.py JSON schema，writer.py 解析 memory_updates 并调 _apply_updates，更新 3 个测试 mock
    status: completed
  - id: p1-supervisor-rules
    content: Supervisor parse_user_input 增加关键词规则匹配层（继续/不行/生成全文共 5 条规则），LLM 解析仅作兜底
    status: completed
  - id: p1-critic-progressive
    content: Critic 渐进式阈值：_review_setting 和 _review_segment 根据 iteration_count 动态降低通过门槛
    status: completed
  - id: p2-rag-cache
    content: RAG 检索结果 TTL 缓存：rag_tool.py 增加 MD5-keyed LRU+TLL 缓存，减少 Embedding+Reranker 重复调用
    status: completed
  - id: p2-memory-sliding
    content: 记忆上下文滑动窗口裁剪：build_memory_context 增加 current_turn 参数和裁剪逻辑，writer.py 调用处传参
    status: completed
  - id: p2-config-unify
    content: 配置统一管理：填充 configs/settings.yaml，src/utils/config.py 增加 YAML 读取优先逻辑
    status: completed
  - id: p2-cleanup-old-code
    content: 使用 [subagent:code-explorer] 确认无引用后，删除 tools/、utils/、exchange_rag_agent/、根目录 config.py
    status: completed
    dependencies:
      - p1-merge-story-memory
      - p1-supervisor-rules
      - p1-critic-progressive
      - p2-rag-cache
      - p2-memory-sliding
      - p2-config-unify
---

## P1：减少 LLM 调用次数（3 项）

将每轮正常 5 次 LLM 调用降至 2~3 次。

### 1.1 合并 story_driver 剧情生成 + 记忆提取为 1 次 LLM
当前 story_driver 先调 LLM 生成 JSON（segment+options），再调 `extract_memory_updates` 调一次 LLM 提取记忆。改为一次 LLM 调用同时产出两者，省 1 次/轮。

### 1.2 Supervisor 规则匹配优先、LLM 兜底
常见输入（"继续"、"不行"、"生成全文"等）用关键词正则匹配，规则无法判断时才调 LLM。省 0~1 次/轮，LLM 调用率降至 20% 以下。

### 1.3 Critic 渐进式阈值
根据 `iteration_count` 动态降低通过门槛（第 1 次 6 分、第 2 次 5 分、第 3 次 4 分），减少不必要的人工中断和重写循环。

## P2：RAG 缓存与基础优化（4 项，排除日志系统）

### 2.1 RAG 检索结果 TTL 缓存
对 `retrieve()` 的查询结果做进程内 LRU 缓存（MD5 key，TTL=300s），减少 Embedding + Reranker API 重复调用。

### 2.2 记忆上下文滑动窗口裁剪
`build_memory_context` 中增加裁剪：角色仅保留最近 5 轮内出现过的，伏笔/笔记仅保留最近 10 条，控制 prompt token 不随轮次线性增长。

### 2.3 配置统一管理
填充 `configs/settings.yaml` 为单一配置源，`src/utils/config.py` 优先读 YAML，`.env` 仅覆盖敏感信息。

### 2.4 清理旧版代码
确认无引用后删除 `tools/`、`utils/`、`exchange_rag_agent/`、根目录 `config.py`。


## 技术方案

### P1 实施详情

#### 1.1 合并 story_driver 剧情生成 + 记忆提取

**改动的文件**：

- `src/prompts/writer_prompt.py` [MODIFY]：STORY_DRIVER_PROMPT 的 JSON 输出示例增加 `memory_updates` 字段，结构与现有 `MEMORY_EXTRACT_PROMPT` 输出一致（`character_updates`, `new_plot_threads`, `resolved_threads`, `new_foreshadowing`, `fulfilled_foreshadowing`, `timeline_events`, `world_notes`）

- `src/agents/writer.py` [MODIFY]：
  - 导入变更：`from src.tools.memory import ... , _apply_updates`（`extract_memory_updates` 改为 `_apply_updates`）
  - 第 72-82 行解析 JSON 后新增：`memory_updates = data.get("memory_updates", {})`
  - 第 107-113 行将 `memory = extract_memory_updates(...)` 替换为 `if memory_updates: memory = _apply_updates(memory, memory_updates, turn)`

- `tests/test_agents.py` [MODIFY]：3 个 `TestStoryDriverNode` 测试用例
  - 移除 `@patch("src.agents.writer.extract_memory_updates")` 装饰器及其 `mock_extract` 形参
  - `mock_llm.return_value` 的 JSON 中增加 `memory_updates` 字段（空值 `{}` 即可，因合并后 memory 由 `_apply_updates` 直接处理，不影响断言）

- `src/tools/memory.py`：无代码改动。`_apply_updates` 已存在于模块顶层，测试通过 `from src.tools.memory import _apply_updates` 直接导入，不受 writer 移除引用影响。`extract_memory_updates` 保留（外部调用方不影响）。

#### 1.2 Supervisor 规则匹配

**改动的文件**：`src/agents/supervisor.py` [MODIFY]

在 `parse_user_input` 函数第 34 行（通用选项 A/B/C/D 匹配之后）第 36 行（兜底 LLM 调用之前）插入约 12 行规则匹配：

```python
# 关键词规则匹配（优先级次于特殊指令、高于 LLM 解析）
COMMON_RULES = [
    (r"继续|然后呢|下一步|接着说|好的|嗯|对", {"action": "select_option", "selected_option": "A"}),
    (r"不行|换一个|重来|不好|不要|算了", {"action": "backtrack", "selected_option": None}),
    (r"生成全文|写完整|全部|完本|完结", {"action": "generate_full", "selected_option": None}),
    (r"确认|可以|就这样|没问题|很好", {"action": "free_input", "selected_option": None}),
    (r"改一下|换个思路|不同的|修改|调整", {"action": "free_input", "selected_option": None}),
]
for pattern, result in COMMON_RULES:
    if re.search(pattern, user_input):
        return result
```

匹配成功直接返回，不再调用 LLM。匹配失败则 fallthrough 到现有 LLM 兜底逻辑。

#### 1.3 Critic 渐进式阈值

**改动的文件**：`src/agents/reviewer.py` [MODIFY]

两处改动：

1. `_review_setting`（第 64-68 行）：
   - 原：`if not passed and score < PASS_THRESHOLD and iteration_count < max_iterations:`
   - 改：`effective_threshold = max(PASS_THRESHOLD - iteration_count, 4)` + 用 `effective_threshold` 替代 `PASS_THRESHOLD`

2. `_review_segment`（第 146-150 行）：
   - 同上改动

3. `CRITIC_PROMPT.format(pass_threshold=...)` 传入动态值：`pass_threshold=effective_threshold`

确保 `PASS_THRESHOLD` 常量不变，仅运行时计算 `effective_threshold`。

### P2 实施详情

#### 2.1 RAG 检索结果缓存

**改动的文件**：`src/tools/rag_tool.py` [MODIFY]

在文件顶部（import 块之后）新增 ~30 行 TTL 缓存实现：

```python
import hashlib
import time

class _TTLCache:
    def __init__(self, maxsize=128, ttl=300):
        self._cache = {}
        self._maxsize = maxsize
        self._ttl = ttl
    def get(self, key):
        if key in self._cache:
            val, ts = self._cache[key]
            if time.time() - ts < self._ttl:
                return val
            del self._cache[key]
        return None
    def set(self, key, value):
        if len(self._cache) >= self._maxsize:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]
        self._cache[key] = (value, time.time())

_rag_cache = _TTLCache()
```

在 `retrieve()` 函数（第 89 行）开头增加缓存查询：

```python
def retrieve(query: str, top_k: int = RERANK_TOP_K) -> str:
    cache_key = hashlib.md5(query.encode()).hexdigest()
    cached = _rag_cache.get(cache_key)
    if cached is not None:
        return cached
    # ... 原逻辑（向量检索 + Reranker）...
    result = "\n\n---\n\n".join(chunk.page_content for chunk in top_chunks)
    if result:
        _rag_cache.set(cache_key, result)
    return result
```

无外部依赖，纯标准库实现。缓存未命中时行为与原逻辑完全一致。

#### 2.2 记忆上下文滑动窗口裁剪

**改动的文件**：

- `src/tools/memory.py` [MODIFY]：`build_memory_context` 函数增加 `current_turn` 参数和裁剪逻辑

```python
def build_memory_context(memory: MemoryState, current_turn: int = None) -> str:
    MEMORY_WINDOW = 5
    MAX_NOTES = 10
    MAX_FORES = 10

    chars = memory.get("characters", [])
    if current_turn is not None:
        chars = [c for c in chars if c.get("last_appearance", 0) >= current_turn - MEMORY_WINDOW]

    threads = [t for t in memory.get("plot_threads", []) if t.get("status") == "active"]

    pending = [f for f in memory.get("foreshadowing", []) if f.get("status") == "pending"]
    pending = pending[-MAX_FORES:]

    timeline = memory.get("timeline", [])
    
    notes = memory.get("world_notes", [])[-MAX_NOTES:]
    # 注意：world_notes 不在现有 build_memory_context 输出中，标记为未来扩展
    # 当前仅 chars / pending 做了裁剪，timeline 仍保留最近 5 条
```

- `src/agents/writer.py` [MODIFY]：第 38 行 `build_memory_context(memory)` → `build_memory_context(memory, current_turn=turn)`

`build_memory_context` 的签名变更后，现有测试中不传 `current_turn` 的调用（`test_tools.py`）行为不变（`current_turn=None`，走旧路径）。

#### 2.3 配置统一管理

**改动的文件**：

- `configs/settings.yaml` [MODIFY]：填充完整配置项（llm, story, quality, rag, memory 小节，具体值从 `.env` 当前默认值同步）

- `src/utils/config.py` [MODIFY]：在 `load_dotenv()` 之后、常量定义之前增加 YAML 读取逻辑。使用标准库 `pathlib.Path` 定位 `configs/settings.yaml`，`yaml.safe_load()` 解析。常量保持 `os.getenv()` 优先（环境变量覆盖 YAML），YAML 值作为二级默认值。

```python
import yaml

_config_path = Path(__file__).resolve().parent.parent.parent / "configs" / "settings.yaml"
_settings = {}
if _config_path.exists():
    with open(_config_path, "r", encoding="utf-8") as f:
        _settings = yaml.safe_load(f) or {}
```

#### 2.4 清理旧版代码

**使用 `[subagent:code-explorer]` 确认无引用后删除**：

已确认：
- `tests/` 中无任何 `from tools.` / `from utils.` / `from exchange_rag_agent` 导入
- `src/` 中 `from tools.` / `from utils.` 仅作为注释（`rag_tool.py` 第 3 行注释、`document_util.py` 第 3 行注释）
- `server.py` 中无旧版路径引用
- 根目录 `config.py`：内容与 `src/utils/config.py` 重复且缺少 `MCP_BING_ENABLED` 配置

删除目标：
- `tools/`（整个目录，含 `__init__.py`, `memory.py`）
- `utils/`（整个目录，含 `__init__.py`, `llm.py`）
- `exchange_rag_agent/`（整个目录，5 个文件）
- 根目录 `config.py`

### 实施顺序与依赖关系

```
1.1 合并story_driver ───── 可独立 ─── 需同步改测试
1.2 Supervisor规则 ─────── 可独立
1.3 Critic渐进阈值 ─────── 可独立
2.1 RAG缓存 ────────────── 可独立
2.2 记忆裁剪 ───────────── 可独立（需改writer.py一处调用）
2.3 配置统一 ───────────── 可独立
2.4 旧版清理 ───────────── 需在全部改动之后，用code-explorer最终确认
```

各任务互不阻塞，可按任意顺序执行。推荐先执行 P1 再执行 P2。

### 预期效果

| 指标 | 优化前 | P1 后 | P1+P2 后 |
|------|--------|-------|----------|
| 每轮 LLM 调用（正常） | 5 次 | 2~3 次 | 2~3 次 |
| 每轮 LLM 调用（最坏） | 11+ 次 | 5~7 次 | 5~7 次 |
| RAG API 调用/轮 | 1 次 | 1 次 | 0.4 次（缓存） |
| 记忆 token 随轮次增长 | O(N) | O(N) | O(1) |
| 端到端响应时间 | 基准 | 缩短 40%~50% | 缩短 50%~60% |


## Agent Extensions

### SubAgent
- **code-explorer**: 在旧版代码清理（2.4）之前最终确认 `tools/`、`utils/`、`exchange_rag_agent/`、根目录 `config.py` 在 `src/`、`tests/`、`server.py` 中无运行时引用，确保删除安全。

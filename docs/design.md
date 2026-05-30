# MSInsight Agent Harness 详细设计文档

## 1. 文档目的

本文档基于 `docs/requirements.md`，定义 `msinsight_agent` 从原有 DAG/MCP 流程编排工程升级为上层 **Agent Harness / Task Orchestrator** 的详细设计。

本设计覆盖：

- 总体架构与职责边界
- 后端核心组件设计
- 意图识别与 ExecutionPlan 设计
- RAG / MCP / LLM Adapter 契约
- Orchestrator 状态机与主流程
- Evidence Store、会话、报告、反馈持久化设计
- SSE 事件与 HTTP API 契约
- 前端展示设计
- 错误降级、可观测性、安全和测试策略
- 分阶段实施建议

## 2. 设计原则

### 2.1 分层边界

```text
用户 / React 前端
   ↓
Agent Harness
   ├── 用户交互
   ├── 意图识别
   ├── ExecutionPlan
   ├── 会话管理
   ├── RAG 调用
   ├── MCP 调用
   ├── Evidence Store
   ├── 诊断结论融合
   └── 报告生成
   ↓                      ↓
MS-RAG                  MSInsight MCP
知识依据                 profiling 工具执行与 playbook 控制
```

职责边界：

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| Agent Harness | 用户任务、路由、计划、会话、证据融合、报告、SSE 展示 | 不维护 MCP 内部 playbook 步骤链，不直接调用 C++ profiling 后端 |
| MS-RAG | 文档检索、知识问答、来源引用、相关主题 | 不执行 profiling 工具，不生成最终实测诊断结论 |
| MSInsight MCP | profiling playbook、工具执行、参数校验、下一步导航 | 不管理前端会话，不做 RAG 证据融合，不生成最终审计报告 |

### 2.2 MCP 优先诊断

分析类请求默认路径：

```text
用户分析问题
  ↓
IntentRouter 识别 diagnosis / profiling_analysis
  ↓
创建 ExecutionPlan
  ↓
MCP search_profiler_tools
  ↓
MCP execute_profiler_tool
  ↓
保存 MCP observation
  ↓
按条件调用 RAG retrieve 增强解释 / 建议 / 报告引用
  ↓
融合 evidence 生成阶段结论或报告
```

RAG 不应在分析类请求中抢先给出纯知识建议，除非：

- MCP 不可用且用户同意降级；
- MCP 结果需要知识解释；
- 用户明确要求解释、依据或报告；
- 报告生成需要知识引用；
- MCP 结果置信度不足，需要补充定位经验。

### 2.3 第一阶段不做自由多 Agent

第一阶段采用：

```text
Single Orchestrator Agent + RAG Expert Service + MCP Expert Service
```

不实现多个自由对话 Agent。后续如需并行通信、算子、数据加载、系统资源等维度分析，再演进为结构化 worker 模式。

## 3. 总体架构

### 3.1 组件图

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Agent React Frontend                         │
│ ChatView / SessionList / TraceTimeline / EvidencePanel / ReportView  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP + SSE
┌──────────────────────────────▼───────────────────────────────────────┐
│                         FastAPI Agent API                            │
│ /api/stream /api/sessions /api/reports /api/config /api/feedback      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────┐
│                         Orchestrator Core                            │
│                                                                      │
│ IntentRouter ── ExecutionPlanner ── Orchestrator ── InteractionPolicy │
│      │               │                    │                 │         │
│      │               │                    │                 │         │
│ SessionStore ◀──── EvidenceStore ◀──── ReportGenerator ◀────┘         │
│      │                                                               │
│ HealthProbe / Observability / ErrorClassifier                         │
└───────────────┬────────────────────────────────────┬─────────────────┘
                │                                    │
┌───────────────▼──────────────┐       ┌─────────────▼─────────────────┐
│          RAG Adapter          │       │           MCP Gateway          │
│ MS-RAG HTTP API               │       │ MCP stdio / SSE / WebSocket    │
│ /api/v1/retrieve              │       │ search_profiler_tools          │
│ /api/v1/qa                    │       │ execute_profiler_tool          │
└───────────────┬──────────────┘       └─────────────┬─────────────────┘
                │                                    │
┌───────────────▼──────────────┐       ┌─────────────▼─────────────────┐
│            MS-RAG             │       │          MSInsight MCP          │
│ retrieve / qa / sources       │       │ playbook / Step Navigator / C++ │
└──────────────────────────────┘       └───────────────────────────────┘
```

### 3.2 后端目录设计

当前工程已有多数基础模块，建议在现有结构上演进：

```text
agent-service/src/
├── adapters/
│   ├── rag_client.py              # MS-RAG HTTP Client
│   ├── mcp_gateway.py             # MCP meta tools Gateway
│   ├── mcp_response_parser.py     # MCP 文本/结构化返回归一化
│   └── llm_classifier.py          # 可选：LLM 结构化意图分类
│
├── core/
│   ├── orchestrator.py            # 主调度器
│   ├── intent_router.py           # 规则优先 + LLM fallback 意图识别
│   ├── execution_planner.py       # ExecutionPlan 创建与更新
│   ├── interaction_policy.py      # 自动执行 / 人工确认策略
│   ├── report_generator.py        # 基于 evidence 的 Markdown 报告
│   └── dag/                       # 保留为通用执行能力，不再负责编排 MCP playbook
│
├── models/
│   ├── orchestration.py           # Intent / PendingInput / SSE / Plan contracts
│   ├── evidence.py                # Evidence model
│   ├── session.py                 # Session / Message
│   ├── report.py                  # Report model
│   └── config.py                  # RAG / MCP / Orchestrator config
│
├── storage/
│   ├── session_store.py           # SQLite sessions.db 统一持久化
│   └── config_store.py            # config.yaml 读取
│
├── api/routes/
│   ├── streaming.py               # SSE message / continue
│   ├── sessions.py                # 会话历史
│   ├── reports.py                 # 报告查询
│   ├── config.py                  # 配置查询
│   ├── feedback.py                # 用户反馈
│   └── error_handling.py          # 系统状态 / 熔断状态
│
├── mcp/transports/                # stdio / sse / websocket / http transport
├── llm/                           # LLM provider adapters
├── observability/                 # logger / metrics / health
└── main.py
```

## 4. 核心数据模型

### 4.1 IntentDecision

```python
class IntentDecision(BaseModel):
    intent: Literal[
        "chat",
        "knowledge_qa",
        "knowledge_retrieve",
        "diagnosis",
        "profiling_analysis",
        "continue_analysis",
        "report_generation",
        "feedback",
        "clarification",
    ]
    confidence: float
    reason: str
    extracted: dict
```

说明：

- `confidence` 表示路由器对意图分类的把握，不表示最终答案正确率。
- `extracted` 保存路径、问题类型、候选 playbook、报告触发词等结构化信息。

推荐阈值：

| 区间 | 行为 |
| --- | --- |
| `confidence >= 0.85` | 直接执行对应路径 |
| `0.60 <= confidence < 0.85` | 调用 LLM 结构化分类或结合 session context 二次判断 |
| `confidence < 0.60` | 不调用 RAG/MCP，向用户澄清 |

### 4.2 ExecutionPlan

ExecutionPlan 是每轮请求的可审计执行计划，应支持历史回看、失败恢复、前端完整展示。

```python
class ExecutionPlan(BaseModel):
    id: str
    session_id: str
    user_message_id: str
    intent: str
    status: Literal["pending", "running", "waiting_user", "completed", "failed", "cancelled"]
    goal: str
    steps: list[ExecutionStep]
    current_step_id: str | None
    evidence_ids: list[str]
    created_at: datetime
    updated_at: datetime
    metadata: dict
```

```python
class ExecutionStep(BaseModel):
    id: str
    plan_id: str
    type: Literal[
        "chat_response",
        "rag_qa",
        "rag_retrieve",
        "mcp_search",
        "mcp_execute",
        "user_input",
        "evidence_fusion",
        "report_generation",
        "fallback_decision",
    ]
    name: str
    status: Literal["pending", "running", "waiting_user", "completed", "failed", "skipped"]
    input: dict
    output: dict | None
    evidence_ids: list[str]
    error: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    elapsed_ms: int | None
    metadata: dict
```

### 4.3 PendingInput

```python
class PendingInput(BaseModel):
    id: str
    session_id: str
    plan_id: str | None
    step_id: str | None
    input_type: Literal["text", "choice", "path", "confirm", "params"]
    question: str
    reason: str
    options: list[PendingInputOption]
    recommended_value: str | None
    status: Literal["pending", "resolved", "cancelled"]
    metadata: dict
    created_at: datetime
    resolved_at: datetime | None
```

### 4.4 Evidence

```python
class Evidence(BaseModel):
    id: str
    session_id: str
    plan_id: str | None
    step_id: str | None
    type: Literal[
        "rag_evidence",
        "mcp_observation",
        "user_input",
        "agent_conclusion",
        "system_event",
    ]
    source: str
    content: str
    summary: str | None
    confidence: Literal["high", "medium", "low", "unknown"]
    metadata: dict
    created_at: datetime
```

#### RAG Evidence metadata

```json
{
  "query": "通信慢 快慢卡 msprof 定位流程",
  "score": 0.82,
  "doc_id": "doc_xxx",
  "chunk_id": "chunk_xxx",
  "title": "通信性能定位指南",
  "section_title": "快慢卡定位",
  "path": "corpus/performance/xxx.md",
  "url": null,
  "vector_score": 0.76,
  "keyword_score": 0.55,
  "final_score": 0.82,
  "rank": 1,
  "retriever": "ms_rag.retrieve",
  "raw": {
    "item": {}
  }
}
```

#### MCP Observation metadata

```json
{
  "mcp_tool": "execute_profiler_tool",
  "internal_tool": "communication_duration_iterations",
  "arguments": {},
  "playbook_id": "fast_slow_rank",
  "step": 2,
  "progress": {
    "completed": 2,
    "total": 5,
    "percentage": 40
  },
  "next_step": {
    "tool_name": "get_units_in_range",
    "schema": {}
  },
  "elapsed_ms": 1800,
  "status": "completed",
  "raw": {}
}
```

## 5. 持久化设计

第一阶段沿用 `sessions.db`，在现有表基础上扩展 `execution_plans` 和 `execution_steps`。

### 5.1 sessions

当前表可继续保留：

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  state TEXT DEFAULT 'IDLE',
  context TEXT
);
```

建议后续演进增加字段，或继续放入 `context` JSON：

```json
{
  "user_goal": "分析 profiling 是否存在快慢卡",
  "current_intent": "profiling_analysis",
  "current_stage": "executing_mcp",
  "active_playbook_id": "fast_slow_rank",
  "active_plan_id": "plan_xxx",
  "pending_input_id": "pin_xxx"
}
```

### 5.2 messages

```sql
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  metadata TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

`metadata` 建议保存：

```json
{
  "plan_id": "plan_xxx",
  "intent": "profiling_analysis",
  "state": "completed"
}
```

### 5.3 execution_plans

```sql
CREATE TABLE IF NOT EXISTS execution_plans (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  user_message_id TEXT,
  intent TEXT NOT NULL,
  status TEXT NOT NULL,
  goal TEXT,
  current_step_id TEXT,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_execution_plans_session ON execution_plans(session_id);
```

### 5.4 execution_steps

```sql
CREATE TABLE IF NOT EXISTS execution_steps (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  input_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  error_json TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT,
  completed_at TEXT,
  elapsed_ms INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (plan_id) REFERENCES execution_plans(id),
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_execution_steps_plan ON execution_steps(plan_id);
```

### 5.5 evidence

现有表可继续使用，建议后续增加 `plan_id`、`step_id`：

```sql
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  plan_id TEXT,
  step_id TEXT,
  type TEXT NOT NULL,
  source TEXT NOT NULL,
  content TEXT NOT NULL,
  summary TEXT,
  confidence TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_plan ON evidence(plan_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(type);
```

### 5.6 pending_inputs

```sql
CREATE TABLE IF NOT EXISTS pending_inputs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  plan_id TEXT,
  step_id TEXT,
  input_type TEXT NOT NULL,
  question TEXT NOT NULL,
  reason TEXT,
  options_json TEXT NOT NULL DEFAULT '[]',
  recommended_value TEXT,
  status TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

### 5.7 reports

```sql
CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  plan_id TEXT,
  format TEXT NOT NULL,
  content TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

### 5.8 feedback

```sql
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  report_id TEXT,
  adopted INTEGER,
  comment TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  FOREIGN KEY (report_id) REFERENCES reports(id)
);
```

## 6. 意图识别设计

### 6.1 策略

第一阶段采用“规则优先 + LLM 结构化分类兜底 + 低置信度澄清”。

```text
用户消息
  ↓
如果存在 pending input：优先进入 continue_analysis
  ↓
规则分类
  ├─ 高置信度：直接返回 IntentDecision
  ├─ 中置信度：调用 LLM structured classify
  └─ 低置信度：clarification
```

### 6.2 规则分类优先级

| 优先级 | 条件 | intent |
| --- | --- | --- |
| 1 | 会话存在未解决 pending input | `continue_analysis` |
| 2 | 包含“报告 / 总结成报告 / 导出 / 整理成方案” | `report_generation` |
| 3 | 包含 profiling 路径、json、trace、profile、e2e 且有“分析/诊断/快慢卡/通信慢” | `profiling_analysis` |
| 4 | 包含“分析/诊断/定位/瓶颈/快慢卡/通信慢/算子慢” | `diagnosis` |
| 5 | 包含“找资料/检索/相关文档/依据” | `knowledge_retrieve` |
| 6 | 包含“怎么/如何/是什么/参数/用法/msprof/MindStudio” | `knowledge_qa` |
| 7 | 问候、能力询问 | `chat` |
| 8 | 无法判断 | `clarification` |

### 6.3 LLM 结构化分类

LLM 仅用于分类，不直接执行工具。

输出格式：

```json
{
  "intent": "profiling_analysis",
  "confidence": 0.83,
  "reason": "用户要求分析 profiling 路径是否存在快慢卡问题",
  "extracted": {
    "path": "D:/data/verl_0118/profile/1/e2e",
    "problem_type": "fast_slow_rank",
    "requires_report": false
  }
}
```

安全约束：

- LLM 分类结果必须经过 schema 校验。
- 低于 `low_confidence_threshold=0.60` 时不调用外部服务。
- LLM 不决定是否绕过 MCP 或直接调用 MCP 内部工具。

### 6.4 普通聊天策略

普通聊天使用固定产品说明模板，不调用 LLM、RAG、MCP，不生成诊断报告。

示例回复：

```text
我是 MSInsight Agent Harness，可以帮助你：
1. 查询 msprof / MindStudio / 昇腾性能定位知识；
2. 基于 profiling 数据调用 MSInsight MCP 执行诊断；
3. 汇总 RAG 知识依据和 MCP 实测结果生成可审计报告。
如果你要分析 profiling，请提供文件或目录路径以及希望定位的问题。
```

## 7. ExecutionPlan 生成策略

### 7.1 Chat Plan

```text
step_1 chat_response
```

不创建 RAG/MCP step。

### 7.2 Knowledge QA Plan

```text
step_1 rag_qa 或 rag_retrieve
step_2 evidence_fusion
step_3 answer_response
```

默认不生成持久化 report。用户明确要求“整理成报告/方案/文档”时增加：

```text
step_4 report_generation
```

### 7.3 Profiling Analysis Plan

```text
step_1 mcp_search                 search_profiler_tools
step_2 user_input?                缺路径 / 多 playbook / 参数不完整时
step_3 mcp_execute                execute_profiler_tool
step_4 mcp_execute*               根据 MCP next_step 自动推进，最多 max_auto_steps
step_5 rag_retrieve?              按条件后置增强
step_6 evidence_fusion            生成阶段结论
step_7 report_generation?         按条件生成报告
```

### 7.4 Report Plan

```text
step_1 load_session_evidence
step_2 rag_retrieve?              需要引用增强时
step_3 report_generation
step_4 report_ready
```

## 8. Orchestrator 主流程设计

### 8.1 handle_message

```python
async def handle_message(session_id: str | None, message: str):
    session = create_or_load_session(session_id)
    user_msg = save_message(session, "user", message)
    yield message_start

    intent = intent_router.route(message, session)
    save_user_input_evidence(intent)
    yield intent_detected

    plan = execution_planner.create_plan(session, user_msg, intent)
    save_plan(plan)
    yield execution_plan_created

    if intent.intent == "chat":
        async for event in run_chat_plan(plan):
            yield event
    elif intent.intent in {"knowledge_qa", "knowledge_retrieve"}:
        async for event in run_knowledge_plan(plan):
            yield event
    elif intent.intent in {"diagnosis", "profiling_analysis"}:
        async for event in run_diagnosis_plan(plan):
            yield event
    elif intent.intent == "report_generation":
        async for event in run_report_plan(plan):
            yield event
    else:
        yield user_input_required

    save_agent_message()
    yield message_end
```

### 8.2 run_diagnosis_plan

```python
async def run_diagnosis_plan(plan):
    search = await mcp_gateway.search_profiler_tools(plan.goal)
    save_mcp_evidence(search)
    yield mcp_tool_result

    if search.requires_user_choice:
        create_pending_input(resume_action="select_playbook")
        yield user_input_required
        return

    if missing_path(plan):
        create_pending_input(resume_action="execute_import")
        yield user_input_required
        return

    result = await execute_mcp_chain(
        initial_tool="import_trace_file",
        initial_args={"file_path": extracted_path},
        max_auto_steps=config.max_auto_steps,
    )

    if should_call_rag_after_mcp(result):
        rag = await rag_client.retrieve(build_rag_query(result))
        save_rag_evidence(rag)
        yield rag_retrieval

    conclusion = fuse_evidence()
    save_agent_conclusion_evidence(conclusion)
    yield analysis_result

    if should_generate_report(plan, conclusion):
        report = report_generator.generate(session_evidence)
        save_report(report)
        yield report_ready
```

### 8.3 execute_mcp_chain

```python
async def execute_mcp_chain(current_tool, current_args):
    auto_count = 0
    while current_tool:
        yield mcp_tool_start
        result = await mcp_gateway.execute_profiler_tool(current_tool, current_args)
        save_mcp_observation(result)
        yield mcp_tool_result

        decision = interaction_policy.decide_after_mcp_result(result, auto_count)

        if decision.action == "continue_auto":
            auto_count += 1
            current_tool = result.next_step.tool_name
            current_args = resolve_args(result.next_step.schema)
            continue

        if decision.action == "require_user_input":
            save_pending_input(decision.pending_input)
            yield user_input_required
            return

        if decision.action == "stop_and_summarize":
            yield analysis_result
            return

        if decision.action == "fail":
            save_system_event()
            yield error
            return
```

## 9. 状态机设计

### 9.1 Session State

```text
idle
  ↓
intent_detected
  ├─ chat ───────────────────────────────▶ completed
  ├─ knowledge ─▶ retrieving_knowledge ─▶ completed
  ├─ report ────▶ reporting ─────────────▶ completed
  └─ diagnosis/profiling
        ↓
     searching_playbook
        ├─ mcp_unavailable ─▶ waiting_user_input? / completed_with_degradation
        ├─ need_playbook_choice ─▶ waiting_user_input
        └─ ready
             ↓
          executing_mcp
             ├─ need_params / confirm ─▶ waiting_user_input
             ├─ max_auto_steps ───────▶ analyzing
             ├─ playbook_done ────────▶ analyzing
             └─ error ────────────────▶ failed / waiting_user_input
                  ↓
              retrieving_knowledge?
                  ↓
              analyzing
                  ↓
              reporting?
                  ↓
              completed
```

### 9.2 Plan / Step Status

| 状态 | 含义 |
| --- | --- |
| `pending` | 已创建，未执行 |
| `running` | 正在执行 |
| `waiting_user` | 等待用户补充输入或确认 |
| `completed` | 执行完成 |
| `failed` | 执行失败 |
| `skipped` | 条件不满足，跳过 |
| `cancelled` | 用户取消或新计划覆盖 |

## 10. RAG Adapter 设计

### 10.1 retrieve

调用：

```http
POST {rag.base_url}/api/v1/retrieve
```

Request:

```json
{
  "query": "通信慢 快慢卡 msprof 定位流程",
  "top_k": 5
}
```

归一化输出：

```python
class RAGRetrieveResult(BaseModel):
    query: str
    results: list[RAGRetrieveItem]
    elapsed_ms: int | None
    raw: dict
```

```python
class RAGRetrieveItem(BaseModel):
    content: str
    score: float | None
    source: dict
    metadata: dict
    raw: dict
```

字段映射策略：

| 标准字段 | 来源优先级 |
| --- | --- |
| `doc_id` | `source.doc_id` → `item.doc_id` |
| `chunk_id` | `source.chunk_id` → `item.chunk_id` → `metadata.chunk_id` |
| `title` | `source.title` → `item.doc_title` → `item.title` → `metadata.title` |
| `section_title` | `source.section_title` → `item.section_title` → `metadata.section_title` |
| `path` | `source.path` → `item.path` → `item.file_path` → `item.source_url` |
| `url` | `source.url` → `item.source_url` |
| `score` | `item.score` → `item.similarity` → `item.final_score` |

必须保存 raw item，避免审计信息丢失。

### 10.2 qa

调用：

```http
POST {rag.base_url}/api/v1/qa
```

使用场景：

- 纯知识问答；
- MCP 不可用且用户同意降级；
- 用户明确要求“直接解释概念”。

纯知识问答默认返回当前回答，不创建持久化报告。

## 11. MCP Gateway 设计

### 11.1 transport 策略

第一阶段优先 stdio，同时保留 SSE / WebSocket / HTTP 配置能力。

| transport | 启动方式 | 健康检查 | 请求执行 |
| --- | --- | --- | --- |
| stdio | Agent 按需拉起 MCP 子进程 | 后台可短暂拉起 initialize/list_tools 后关闭 | 请求时建立或复用 stdio transport |
| SSE | MCP 外部手动启动 | 后台 ping / list_tools | 请求时连接远程 MCP |
| WebSocket | MCP 外部手动启动 | 后台 ping / list_tools | 请求时连接远程 MCP |
| HTTP | MCP 外部手动启动 | HTTP health | 请求时 HTTP call |

### 11.2 tools 加载时机

采用“启动后后台预检 + 请求时按需连接”。

- Agent Harness 启动时不强制长期持有 MCP stdio 子进程。
- 后台预检负责验证：
  - command / args / cwd 配置是否完整；
  - MCP 是否可连接；
  - `search_profiler_tools` 是否存在；
  - `execute_profiler_tool` 是否存在。
- 真实分析请求到来时再建立或复用连接执行工具。
- 预检失败只影响系统状态和分析能力，不影响普通聊天与 RAG 问答。

### 11.3 search_profiler_tools

Adapter 输入：

```json
{
  "query": "分析 D:/data/profile 是否存在快慢卡问题",
  "select_playbook": null
}
```

MCP call：

```json
{
  "name": "search_profiler_tools",
  "arguments": {
    "query": "分析 D:/data/profile 是否存在快慢卡问题"
  }
}
```

归一化输出：

```python
class MCPSearchResult(BaseModel):
    status: str
    text: str
    playbook_candidates: list[dict]
    auto_selected_playbook: str | None
    requires_user_choice: bool
    metadata: dict
    elapsed_ms: int | None
    raw: dict
```

### 11.4 execute_profiler_tool

Adapter 输入：

```json
{
  "tool_name": "import_trace_file",
  "arguments": {
    "file_path": "D:/data/profile/1/e2e"
  }
}
```

MCP call：

```json
{
  "name": "execute_profiler_tool",
  "arguments": {
    "tool_name": "import_trace_file",
    "arguments": {
      "file_path": "D:/data/profile/1/e2e"
    }
  }
}
```

归一化输出：

```python
class MCPToolResult(BaseModel):
    status: str
    tool_name: str | None
    text: str
    next_step: MCPNextStep | None
    requires_user_input: bool
    error: str | None
    elapsed_ms: int | None
    raw: dict
```

## 12. InteractionPolicy 设计

### 12.1 自动执行允许条件

只有同时满足以下条件才自动继续：

1. MCP 返回明确 next_step；
2. next_step 指向只读分析工具；
3. required 参数已由 MCP context、历史用户输入或当前结果补齐；
4. 无 playbook 分支歧义；
5. 无候选项需要用户选择；
6. 无写入、覆盖、删除、启停、提交任务等副作用；
7. `auto_count < max_auto_steps`。

### 12.2 必须请求用户输入的条件

- 缺少 profiling 文件路径；
- MCP 返回参数校验失败；
- MCP 返回多个 playbook 候选；
- MCP 返回多个候选 rank、iteration、step、device 等选项；
- 工具可能写入、删除、覆盖、启动、停止或提交任务；
- 任务可能长时间占用显著资源；
- 路径、目标或执行范围存在歧义；
- 意图识别低置信度。

### 12.3 路径安全策略

Agent Harness 第一阶段只做格式校验：

- 是否为空；
- 是否明显不是路径；
- 是否包含不可接受的控制字符；
- 是否需要用户确认远端路径语义。

不做本地存在性强校验，因为 MCP 可能运行在不同工作目录或远端机器。本地路径可访问性由 MCP 及其安全策略最终判断。

## 13. RAG 后置触发条件

分析链路中，MCP 后置 RAG 的触发条件：

| 条件 | 是否触发 RAG | 说明 |
| --- | --- | --- |
| MCP 完成且需要解释指标含义 | 是 | 检索术语、阈值、定位流程 |
| MCP 发现明确问题 | 是 | 为报告补充知识依据和建议 |
| MCP 返回置信度不足或结论不完整 | 是 | 补充历史经验和排查方向 |
| 用户明确要求“解释/依据/资料/建议” | 是 | 满足用户知识需求 |
| 用户要求生成报告 | 是 | 报告需要引用来源 |
| MCP 不可用 | 询问后触发 | 用户同意后降级为 RAG 知识建议 |
| 普通聊天 | 否 | 固定模板回答 |
| 纯知识问答 | 直接 RAG | 不走 MCP |

## 14. 报告设计

### 14.1 报告与普通回答的区别

| 类型 | 是否每轮都有 | 是否保存 reports 表 | 用途 |
| --- | --- | --- | --- |
| 普通回复 | 是 | 否 | 当前对话展示 |
| 答案总结 | 知识问答中常见 | 默认否 | RAG 结果自然语言总结 |
| 诊断报告 | 条件触发 | 是 | 可回看、可审计、可分享 |

纯知识问答默认不生成持久化报告；用户明确要求“整理成报告/方案/文档”时，才保存 Markdown 报告。

### 14.2 触发条件

生成持久化报告的条件：

- 用户明确要求生成报告；
- MCP 完成关键诊断阶段且发现明确问题；
- 用户要求复盘或分享；
- 会话结束时用户选择沉淀结果；
- 系统策略配置为自动生成阶段报告。

### 14.3 Markdown 结构

```markdown
# 性能诊断报告

## 1. 问题摘要

## 2. 当前结论

## 3. 证据链

### 3.1 MCP 实测证据

### 3.2 RAG 知识依据

### 3.3 用户输入

## 4. 可能根因排序

## 5. 建议下一步操作

## 6. 风险与不确定性

## 7. 引用来源
```

### 14.4 证据表达要求

报告必须区分：

- 已确认事实：MCP observation、用户输入；
- 基于证据的推断：Agent conclusion；
- 知识依据：RAG evidence；
- 不确定项：仍需用户或工具进一步确认的问题。

## 15. HTTP API 设计

### 15.1 Streaming API

#### 发送消息

```http
POST /api/stream/message
Content-Type: application/json
Accept: text/event-stream
```

Request:

```json
{
  "session_id": "ses_xxx",
  "message": "分析 D:/data/profile/1/e2e 是否存在快慢卡问题",
  "options": {
    "auto_execute": true
  }
}
```

Response: `text/event-stream`

#### 继续执行

```http
POST /api/stream/continue
Content-Type: application/json
Accept: text/event-stream
```

Request:

```json
{
  "session_id": "ses_xxx",
  "input": {
    "pending_input_id": "pin_xxx",
    "type": "path",
    "value": "D:/data/profile/1/e2e"
  }
}
```

### 15.2 Session API

```http
POST /api/sessions
GET /api/sessions
GET /api/sessions/{session_id}
DELETE /api/sessions/{session_id}
```

`GET /api/sessions/{session_id}` 应返回：

```json
{
  "session": {},
  "messages": [],
  "plans": [],
  "evidence": [],
  "reports": [],
  "pending_input": null
}
```

### 15.3 Plan API

建议新增：

```http
GET /api/sessions/{session_id}/plans
GET /api/plans/{plan_id}
GET /api/plans/{plan_id}/steps
```

用于前端历史回看和失败恢复。

### 15.4 Evidence API

建议新增：

```http
GET /api/sessions/{session_id}/evidence
GET /api/evidence/{evidence_id}
```

### 15.5 Report API

```http
GET /api/reports/{report_id}
GET /api/sessions/{session_id}/reports
POST /api/sessions/{session_id}/reports
```

### 15.6 Health / Status API

```http
GET /health
GET /ready
GET /api/error-handling/circuit-breakers
GET /api/error-handling/errors/stats
GET /api/system/status
```

`/api/system/status` 建议聚合：

```json
{
  "agent": "healthy",
  "rag": {
    "enabled": true,
    "status": "healthy",
    "base_url": "http://127.0.0.1:8001"
  },
  "mcp": {
    "enabled": true,
    "status": "unavailable",
    "transport": "stdio",
    "last_error": "Failed to start MCP process"
  },
  "storage": {
    "status": "healthy",
    "sqlite_path": "./sessions/sessions.db"
  }
}
```

## 16. SSE 事件设计

所有事件 envelope：

```json
{
  "event": "mcp_tool_result",
  "event_id": "evt_xxx",
  "session_id": "ses_xxx",
  "timestamp": "2026-05-28T10:00:00Z",
  "data": {}
}
```

### 16.1 事件列表

| 事件 | 触发时机 | 前端用途 |
| --- | --- | --- |
| `message_start` | 开始处理用户消息 | 创建 assistant placeholder |
| `intent_detected` | 意图识别完成 | 展示路由判断 |
| `execution_plan_created` | 计划创建完成 | 展示完整计划 |
| `execution_step_started` | step 开始 | Timeline 置 running |
| `execution_step_completed` | step 完成 | Timeline 置 completed |
| `execution_step_failed` | step 失败 | Timeline 置 failed |
| `rag_retrieval` | RAG 检索完成 | 展示 RAG evidence |
| `mcp_tool_start` | MCP 工具开始 | 展示工具执行中 |
| `mcp_tool_result` | MCP 工具完成 | 展示 MCP observation |
| `user_input_required` | 需要用户输入 | 展示表单/选择/确认 |
| `analysis_result` | 阶段结论 | 展示自然语言分析结果 |
| `report_ready` | 报告生成完成 | 展示报告入口 |
| `error` | 可恢复或不可恢复错误 | 展示错误和降级建议 |
| `message_delta` | 文本增量 | 流式回答 |
| `message_end` | 当前轮结束 | 收尾状态 |

### 16.2 execution_plan_created

```json
{
  "data": {
    "plan_id": "plan_xxx",
    "intent": "profiling_analysis",
    "status": "pending",
    "steps": [
      {
        "id": "step_1",
        "type": "mcp_search",
        "name": "搜索 MCP profiling playbook",
        "status": "pending"
      },
      {
        "id": "step_2",
        "type": "mcp_execute",
        "name": "执行 profiling 导入和分析",
        "status": "pending"
      },
      {
        "id": "step_3",
        "type": "rag_retrieve",
        "name": "按条件检索知识依据",
        "status": "pending"
      }
    ]
  }
}
```

### 16.3 user_input_required

```json
{
  "data": {
    "pending_input_id": "pin_xxx",
    "plan_id": "plan_xxx",
    "step_id": "step_2",
    "input_type": "choice",
    "question": "检测到多个分析剧本，请选择执行路径。",
    "reason": "不同剧本对应不同定位方向，自动选择可能偏离目标。",
    "options": [
      {
        "label": "快慢卡定位",
        "value": "fast_slow_rank",
        "description": "适合定位 rank 间通信耗时差异"
      }
    ],
    "recommended_value": "fast_slow_rank"
  }
}
```

### 16.4 error

```json
{
  "data": {
    "code": "MCP_UNAVAILABLE",
    "message": "MCP 服务不可用，无法基于真实 profiling 数据验证。",
    "recoverable": true,
    "degradation_options": [
      {
        "label": "降级为 RAG 知识建议",
        "value": "fallback_to_rag"
      }
    ],
    "evidence_id": "ev_xxx"
  }
}
```

## 17. 错误分类与降级策略

### 17.1 错误分类

| code | 来源 | recoverable | 处理 |
| --- | --- | --- | --- |
| `INTENT_UNCLEAR` | IntentRouter | 是 | 请求用户澄清 |
| `RAG_UNAVAILABLE` | RAGClient | 是 | 分析链路继续 MCP，并说明缺少知识依据 |
| `MCP_UNAVAILABLE` | MCPGateway | 是 | 询问是否降级为 RAG 知识建议 |
| `MCP_TOOL_FAILED` | MCPGateway | 视情况 | 保存 observation，提示阻塞点 |
| `MCP_PARAM_MISSING` | MCPGateway | 是 | user_input_required |
| `MCP_PLAYBOOK_CHOICE_REQUIRED` | MCPGateway | 是 | user_input_required |
| `PATH_INVALID_FORMAT` | Orchestrator | 是 | 请求用户修正路径 |
| `REPORT_GENERATION_FAILED` | ReportGenerator | 是 | 保留 evidence，提示报告失败 |
| `STORAGE_ERROR` | SessionStore | 否 | 返回错误，避免继续执行 |

### 17.2 MCP 不可用行为

分析类请求中 MCP 不可用时：

1. 保存 `system_event` evidence；
2. 发出 `error` SSE；
3. 询问用户是否降级为 RAG 知识建议；
4. 用户同意后调用 RAG `/retrieve` 或 `/qa`；
5. 回答中必须明确说明：当前结果不是基于真实 profiling 数据验证。

### 17.3 RAG 不可用行为

- 纯知识问答：返回可恢复错误，提示 RAG 不可用；
- 分析诊断：继续 MCP 实测分析，报告中说明缺少知识依据。

## 18. 前端设计

### 18.1 页面结构

```text
App
├── ChatView
│   ├── MessageList
│   ├── TraceTimeline
│   ├── PendingInputPanel
│   └── Composer
├── SessionList
├── EvidencePanel
├── ReportView
└── SystemStatus
```

### 18.2 ChatView

职责：

- 发送 `/api/stream/message`；
- 解析 SSE；
- 展示 assistant 文本；
- 展示错误、等待输入、报告入口；
- 将事件写入 `traceEvents`。

### 18.3 TraceTimeline

展示完整 ExecutionPlan：

- intent；
- step 列表；
- 每个 step 状态；
- RAG / MCP evidence 引用；
- 错误和降级原因；
- 耗时。

### 18.4 EvidencePanel

按类型分组展示 evidence：

- 用户输入；
- MCP observation；
- RAG evidence；
- Agent conclusion；
- system event。

每条 evidence 支持查看：

- summary；
- content；
- metadata；
- raw。

### 18.5 PendingInputPanel

根据 `input_type` 渲染：

| input_type | UI |
| --- | --- |
| `text` | 文本输入框 |
| `path` | 路径输入框 |
| `choice` | Radio / Select |
| `confirm` | 确认 / 取消按钮 |
| `params` | 动态表单 |

### 18.6 ReportView

- Markdown 渲染；
- evidence 引用跳转；
- 报告生成时间；
- 用户反馈入口。

## 19. 配置设计

```yaml
rag:
  enabled: true
  base_url: "http://127.0.0.1:8001"
  retrieve_path: "/api/v1/retrieve"
  qa_path: "/api/v1/qa"
  timeout_seconds: 30
  top_k: 5

mcp:
  enabled: true
  transport: "stdio"
  command: "python"
  args: ["main.py", "--transport", "stdio"]
  cwd: "D:/Project/新建文件夹/mcp"
  timeout_seconds: 60
  health_check_on_startup: true
  health_check_mode: "background"
  required_meta_tools:
    - "search_profiler_tools"
    - "execute_profiler_tool"

orchestrator:
  chat_mode: "fixed_template"
  intent_strategy: "rule_first_llm_fallback"
  high_confidence_threshold: 0.85
  low_confidence_threshold: 0.60
  auto_execute: true
  max_auto_steps: 5
  require_confirmation_for_side_effects: true
  validate_path_mode: "format_only"
  rag_after_mcp_policy: "conditional"
  mcp_unavailable_policy: "ask_before_rag_fallback"
  report_policy: "conditional"

report:
  format: "markdown"
  save_to_session_db: true
  enable_pdf_export: false

storage:
  sqlite_path: "./sessions/sessions.db"
```

## 20. 可观测性设计

### 20.1 日志字段

每条关键日志应包含：

- `request_id`
- `session_id`
- `plan_id`
- `step_id`
- `intent`
- `tool_name`
- `elapsed_ms`
- `status`
- `error_code`

### 20.2 指标

建议指标：

```text
agent_requests_total
agent_intent_classification_total{intent}
agent_rag_requests_total{status}
agent_rag_latency_ms
agent_mcp_tool_calls_total{tool,status}
agent_mcp_latency_ms{tool}
agent_execution_plan_total{status}
agent_pending_input_total{type}
agent_report_generation_total{status}
agent_report_generation_latency_ms
```

### 20.3 敏感信息脱敏

日志、报告、错误返回中不得输出：

- API key；
- Authorization header；
- token；
- 环境变量完整内容；
- 与用户任务无关的系统路径。

## 21. 安全设计

- Agent Harness 不绕过 MCP 路径安全策略。
- 路径只做格式校验，不做本地强存在性判断。
- 副作用工具必须请求用户确认。
- MCP 内部工具名只能来自 `search_profiler_tools` / `execute_profiler_tool` 返回或用户确认，不允许前端直接指定任意内部工具绕过流程。
- 报告只引用当前 session evidence。
- 用户反馈不自动写回 RAG corpus。
- 外部服务错误不暴露完整堆栈给前端，只写入服务端日志。

## 22. 测试设计

### 22.1 单元测试

| 模块 | 测试内容 |
| --- | --- |
| IntentRouter | chat / qa / retrieve / diagnosis / report / clarification 路由 |
| ExecutionPlanner | 不同 intent 生成正确 step |
| InteractionPolicy | 自动执行、用户输入、副作用确认、max_auto_steps |
| RAGClient | 返回字段归一化、raw 保存、错误处理 |
| MCPGateway | search / execute 响应解析、next_step 解析、错误分类 |
| ReportGenerator | evidence 分类、Markdown 结构、引用生成 |
| SessionStore | plans、steps、evidence、reports 持久化 |

### 22.2 集成测试

- Mock RAG + Mock MCP：验证完整 diagnosis 流程；
- Mock MCP 多 playbook：验证用户选择恢复；
- Mock MCP 参数缺失：验证 `user_input_required`；
- RAG 不可用：诊断继续 MCP；
- MCP 不可用：询问是否降级 RAG；
- 历史会话恢复：messages + plans + evidence + reports 可回看；
- 前端 SSE：所有事件可正确渲染。

### 22.3 验收测试

| 场景 | 验收点 |
| --- | --- |
| 普通聊天 | 不调用 RAG/MCP，返回固定产品说明 |
| 知识问答 | 调用 RAG，返回来源，不调用 MCP，不生成报告 |
| profiling 分析 | MCP 优先，必要时 RAG 后置，保存 evidence |
| 多候选 playbook | 展示候选项和推荐，不擅自选择 |
| 参数缺失 | 发出 `user_input_required`，补充后恢复 |
| 报告生成 | 保存 Markdown，引用 evidence，区分实测和知识依据 |
| 系统状态 | RAG/MCP/storage 状态可见，MCP 预检失败不影响聊天 |

## 23. 分阶段实施计划

### Phase 1：需求收敛与文档对齐

- 将 `docs/requirements.md` 的开放问题收敛为已确认决策。
- 更新本文档，明确 MCP 优先、RAG 后置、ExecutionPlan、报告策略。

### Phase 2：核心模型与持久化

- 新增 `ExecutionPlan` / `ExecutionStep` models。
- 扩展 SQLite 表：`execution_plans`、`execution_steps`。
- 为 evidence / pending_inputs / reports 增加 `plan_id`、`step_id`。
- 增加 Session API 返回 plans、evidence、reports。

### Phase 3：路由与计划执行

- 扩展 `IntentType.CHAT`。
- 实现规则优先 + LLM fallback 分类。
- 实现 `ExecutionPlanner`。
- 将诊断流程调整为 MCP 优先。
- 实现 RAG 后置条件判断。

### Phase 4：SSE 与前端过程展示

- 新增 `execution_plan_created`、`execution_step_started`、`execution_step_completed`、`execution_step_failed`。
- 前端新增 TraceTimeline / EvidencePanel / ReportView 增强。
- 历史会话恢复完整 plan 和 evidence。

### Phase 5：健康检查与降级

- 实现 MCP 后台预检。
- 实现 `/api/system/status` 聚合状态。
- 完善 MCP 不可用询问 RAG 降级。
- 完善 RAG 不可用时 MCP 继续执行。

### Phase 6：测试与工业化

- 补齐单元测试、Mock 集成测试、SSE 前端测试。
- 增加可观测指标。
- 增加报告 snapshot 测试。
- 固化验收用例。

## 24. 明确不做事项

第一阶段不做：

- 不重写 MS-RAG 内部检索架构；
- 不重写 MSInsight MCP playbook / Context Board / Step Navigator；
- 不实现自由对话式多 Agent；
- 不绕过 MCP 调用 C++ profiling 后端；
- 不在 Agent Harness 中维护具体 MCP 步骤 DAG；
- 不自动把用户反馈写回 RAG corpus；
- 不实现 PDF 导出；
- 不实现复杂多租户权限系统。

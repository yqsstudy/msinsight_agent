# DiagnosisAgent 工业级上下文机制实施工作流

## 1. 工作流目标

基于：

- `docs/diagnosis_context_requirements.md`
- `docs/diagnosis_context_design.md`

制定 `DiagnosisAgent` 工业级上下文机制的实施工作流。目标是在不破坏现有 MCP meta-tool 架构的前提下，为 agent-service 增加诊断级结构化上下文、参数复用、pending/paused 恢复、回退失效、operation queue、CandidateSet、schema drift、MCP reconciliation、report evidence guard、前端可见性与可观测性。

本计划只描述实施步骤，不直接执行代码修改。

## 2. 实施边界

### 2.1 必须遵守

1. profiling 执行仍然只能通过 `MCPGateway` 调用：
   - `search_profiler_tools`
   - `execute_profiler_tool`
2. 不绕过 MCP service 直接调用 internal tools。
3. MCP service 是 playbook 执行状态、step progress、前置依赖、blocked/stale 判断的真相源。
4. agent-service 负责用户交互上下文、参数复用、LLM compact context、pending/resume、回退失效、报告 evidence guard、前端状态和审计。
5. LLM assistance 只做建议：playbook/query/参数抽取；不得发明 tool/playbook，不得决定状态变更。
6. 当前阶段不做 MCP internal tool 风险等级分类。
7. 第一阶段失效采用线性截断，不做完整 DAG 依赖级失效。
8. 当前报告只使用 effective evidence。

### 2.2 不在本工作流直接执行

- 不实现 MCP service 内部 tool 风险等级。
- 不新增 MCP 顶层工具。
- 不做完整 replay 引擎；先做 audit timeline。
- 不一次性重写全部 Orchestrator；采用可回滚的增量接入。

## 3. 总体实施原则

1. **先建模型与存储，再接主链路**：先让 `DiagnosisContext` 可序列化、可持久化、可测试。
2. **先参数复用，再复杂失效**：优先解决当前每步重复询问的问题。
3. **先后端一致性，再前端增强**：后端事件与状态稳定后再完善 UI。
4. **所有状态变更可审计**：context revision、operation、pending、step、param、evidence 变化都应有 audit event。
5. **所有自动行为有上限**：auto step、reconciliation、queue stale 都必须可控。
6. **保留现有兼容路径**：初期可以保留 `_resolve_step_arguments` 作为 fallback/helper，但主路径迁移到 `ParameterResolver`。
7. **以测试驱动切分提交**：每个 phase 至少包含核心单测或集成测试。

## 4. 阶段总览

| Phase | 名称 | 目标 | 依赖 |
| --- | --- | --- | --- |
| P0 | 基线审计与范围冻结 | 确认当前 DiagnosisAgent、SessionStore、Orchestrator、MCPGateway 状态，冻结实施入口 | 无 |
| P1 | 核心模型与 JSON 序列化 | 增加 DiagnosisContext、ParamProvenance、StepRecord、PendingStepState 等模型 | P0 |
| P2 | 持久化与审计基础 | 增加 diagnosis_contexts、operations、audit_events 存储能力 | P1 |
| P3 | ParameterResolver 与 compact context | 实现上下文参数复用、provenance、LLM compact context | P1 + P2 |
| P4 | DiagnosisAgent Phase 1 接入 | 将 run/resume/execute 接入 DiagnosisContext 与 ParameterResolver | P3 |
| P5 | PendingInputRouter 与 paused 多诊断 | pending 输入先路由，支持 pause/resume/multiple paused | P4 |
| P6 | InvalidationEngine 与 report guard | 支持回退线性失效、effective/invalidated evidence、报告 guard | P4 |
| P7 | OperationQueue 与幂等 | session 内 mutation 串行、FIFO、stale 校验、idempotency | P5 + P6 |
| P8 | CandidateSet 生命周期 | 支持候选集、全局编号、选择解析、来源失效 | P6 + P7 |
| P9 | Schema drift / reconciliation / playbook switch | 处理 schema 变化、MCP blocked/stale、剧本切换 | P7 + P8 |
| P10 | SSE/API 契约与前端 UI | 新增 diagnosis 事件、Context Panel、Queue UI、Paused List | P7-P9 |
| P11 | 可观测性与 metrics | 完成 audit persistence、Prometheus metrics、简化 timeline | P2-P10 |
| P12 | 集成测试、验收与文档收口 | 覆盖关键工业级场景，更新文档 | P1-P11 |

## 5. 依赖关系图

```text
P0 基线审计
  ↓
P1 核心模型
  ↓
P2 持久化与审计基础
  ↓
P3 ParameterResolver + compact context
  ↓
P4 DiagnosisAgent Phase 1 接入
  ├──────────────┬──────────────┐
  ↓              ↓              ↓
P5 PendingRouter P6 Invalidation P7 OperationQueue
  │              │              │
  └──────┬───────┴──────┬───────┘
         ↓              ↓
      P8 CandidateSet   P9 Schema/Reconcile/Switch
         └──────┬───────┘
                ↓
      P10 SSE/API + Frontend
                ↓
      P11 Observability
                ↓
      P12 Tests + Docs
```

## 6. Phase P0：基线审计与范围冻结

### 6.1 目标

明确现有代码状态和接入边界，避免在已有运行产物、旧文档或旧 DAG 逻辑中误改。

### 6.2 任务

#### P0.1 工作区审计

检查：

- `git status --short`
- `agent-service/src/core/agents/diagnosis_agent.py`
- `agent-service/src/core/orchestrator.py`
- `agent-service/src/core/mcp_llm_assistant.py`
- `agent-service/src/adapters/mcp_gateway.py`
- `agent-service/src/storage/session_store.py`
- `agent-service/config/config.yaml`

产出：

- 当前代码变更清单；
- 运行产物排除清单，如 `__pycache__`、`sessions.db`；
- 本次实施的起点 commit / branch；
- 需保护的现有行为清单。

验收：

- 明确哪些文件属于本功能修改范围；
- 明确 generated cache / SQLite 调试数据不作为源代码改动；
- 明确 profiling 主链路仍走 `DiagnosisAgent` + `MCPGateway`。

#### P0.2 当前问题复核

重点确认当前实现：

- `DiagnosisAgent.run()` 只从 `blackboard.get("extracted", {})` 构造薄 context；
- `resume()` 从 pending metadata 的 `context` 恢复薄上下文；
- next step 参数解析只依赖 `message/path/selected_playbook`；
- `extract_parameters_by_schema()` 未接收诊断上下文；
- `Orchestrator.continue_with_input()` 直接调用 agent.resume，未经过 operation queue。

验收：

- 问题与需求文档背景一致；
- 后续每个 phase 都能映射到这些问题。

## 7. Phase P1：核心模型与 JSON 序列化

### 7.1 目标

建立后续模块共享的稳定数据结构，并确保可 JSON 序列化、可持久化、可版本演进。

### 7.2 任务

#### P1.1 新增 diagnosis 包

建议新增：

```text
agent-service/src/core/diagnosis/
├── __init__.py
├── models.py
├── context.py
├── compact.py
└── audit.py
```

验收：

- 包可被 `DiagnosisAgent`、`Orchestrator`、`SessionStore` 引用；
- 不引入 MCP service 反向依赖。

#### P1.2 定义核心模型

目标文件：

- `agent-service/src/core/diagnosis/models.py`

模型：

- `DiagnosisContext`
- `ParamProvenance`
- `StepRecord`
- `PendingStepState`
- `CandidateSet`
- `CandidateItem`
- `DiagnosisOperation`
- `DiagnosisAuditEvent`
- `ReconciliationState`
- `ParameterResolutionResult`
- `ResolvedParameter`
- `ParameterConflict`

验收：

- 字段覆盖 `docs/diagnosis_context_design.md` 第 4 节；
- 所有模型可 Pydantic 序列化/反序列化；
- 支持缺省字段兼容旧 JSON；
- status/type/source/confidence 等字段有明确枚举或 Literal。

#### P1.3 实现 DiagnosisContext 方法

目标文件：

- `agent-service/src/core/diagnosis/context.py`

核心方法：

```python
create(...)
from_json(...)
to_json(...)
increment_revision(...)
set_pending(...)
clear_pending(...)
add_or_update_param(...)
apply_step_result(...)
mark_status(...)
compact_for_llm(...)
```

验收：

- `revision` 在状态变更时递增；
- `known_params` 与 `param_provenance` 一致；
- `apply_step_result` 能记录 completed step、evidence、next_step、produced params；
- invalidated 内容不会进入 active compact context。

#### P1.4 单元测试

新增：

```text
agent-service/tests/core/test_diagnosis_context.py
```

覆盖：

- create / serialize / deserialize；
- param add/update + provenance；
- apply_step_result；
- pending set/clear；
- compact context 基础输出。

## 8. Phase P2：持久化与审计基础

### 8.1 目标

让 diagnosis context、operation 和 audit event 可恢复、可查询、可审计。

### 8.2 任务

#### P2.1 扩展 SessionStore schema

目标文件：

- `agent-service/src/storage/session_store.py`

新增表：

```sql
CREATE TABLE IF NOT EXISTS diagnosis_contexts (
  diagnosis_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  status TEXT NOT NULL,
  context_json TEXT NOT NULL,
  revision INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS diagnosis_operations (
  operation_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  diagnosis_id TEXT,
  idempotency_key TEXT,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  target_pending_id TEXT,
  expected_revision INTEGER,
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT
);
```

```sql
CREATE TABLE IF NOT EXISTS diagnosis_audit_events (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  diagnosis_id TEXT,
  event_type TEXT NOT NULL,
  revision INTEGER,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_diagnosis_contexts_session_status
  ON diagnosis_contexts(session_id, status);
CREATE INDEX IF NOT EXISTS idx_diagnosis_operations_session_status
  ON diagnosis_operations(session_id, status);
CREATE INDEX IF NOT EXISTS idx_diagnosis_audit_session_diag
  ON diagnosis_audit_events(session_id, diagnosis_id, created_at);
```

验收：

- 启动幂等创建；
- 老数据库可安全升级；
- 不破坏现有 sessions/messages/evidence/pending_inputs。

#### P2.2 增加 Store 方法

目标文件：

- `agent-service/src/storage/session_store.py`

新增方法：

```python
create_diagnosis_context(context)
update_diagnosis_context(context)
get_diagnosis_context(diagnosis_id)
get_active_diagnosis_context(session_id)
list_diagnosis_contexts(session_id, status=None)
create_diagnosis_operation(operation)
update_diagnosis_operation(operation)
get_diagnosis_operation(operation_id)
find_operation_by_idempotency_key(session_id, idempotency_key)
list_queued_operations(session_id)
create_diagnosis_audit_event(event)
list_diagnosis_audit_events(session_id, diagnosis_id=None)
```

验收：

- context revision 持久化一致；
- 可按 session 查询 active/paused contexts；
- operation 可按 FIFO 查询；
- audit event 可按时间排序。

#### P2.3 审计事件 writer

目标文件：

- `agent-service/src/core/diagnosis/audit.py`

实现：

```python
DiagnosisAuditWriter.write(event_type, context, payload)
```

验收：

- 支持文档中的 event types；
- 审计写入失败不得静默声称成功，应记录日志并按策略决定是否中断关键流程。

#### P2.4 单元测试

新增/扩展：

```text
agent-service/tests/core/test_diagnosis_context.py
agent-service/tests/storage/test_session_store_diagnosis.py
```

覆盖：

- 表初始化；
- CRUD；
- 旧库升级；
- audit event 查询；
- idempotency lookup。

## 9. Phase P3：ParameterResolver 与 compact context

### 9.1 目标

解决“每个 MCP step 都重复询问用户”的核心问题：在执行 step 前从有效上下文、MCP 输出、用户输入、候选集和 LLM compact context 自动补参。

### 9.2 任务

#### P3.1 实现 compact_for_llm

目标文件：

- `agent-service/src/core/diagnosis/compact.py`
- 或 `context.py`

默认输出：

- user_goal；
- selected_playbook；
- current_tool；
- known_params；
- param_sources；
- latest 3 completed step summaries；
- last MCP result summary；
- active CandidateSet 最多 20 个候选；
- pending 摘要；
- minimal invalidated summary。

默认排除：

- invalidated step details；
- raw MCP result；
- all historical messages；
- all paused contexts；
- obsolete schema args。

验收：

- token 输出有明确上限；
- invalidated details 不进入 LLM；
- 最近 3 步与最多 20 candidates 规则可测。

#### P3.2 实现 ParameterResolver

目标文件：

- `agent-service/src/core/diagnosis/resolver.py`

核心方法：

```python
resolve_for_step(
    context,
    step,
    suggested_args=None,
    current_user_input=None,
    existing_args=None,
) -> ParameterResolutionResult
```

解析顺序：

1. start from suggested/existing args；
2. schema filter；
3. fill from current user explicit input；
4. fill from context.known_params + alias map；
5. fill from latest MCP output summary；
6. fill query/message fields；
7. LLM extraction with compact context；
8. schema/candidate validation；
9. conflict handling；
10. missing required check。

验收：

- path aliases 自动复用：`path/file_path/filepath/trace_path/trace_file/data_path`；
- query aliases 自动复用：`query/question/user_query/goal`；
- 用户显式输入优先于 MCP suggested args；
- LLM 不能覆盖高可信 known params；
- 只影响 pending 的冲突可直接覆盖 pending args；
- 需要回退的冲突返回 conflict，不直接修改 context。

#### P3.3 调整 LLM assistant 接口

目标文件：

- `agent-service/src/core/mcp_llm_assistant.py`

将：

```python
extract_parameters_by_schema(user_input, tool_schema, existing_args)
```

扩展为：

```python
extract_parameters_by_schema(user_input, tool_schema, existing_args, context=None)
```

要求：

- 只返回 schema properties 内字段；
- 不使用 invalidated context；
- 不覆盖 existing_args，除非用户明确修改；
- 出错时降级为空 dict。

验收：

- 旧调用兼容；
- 新 prompt 包含 compact context；
- schema 外字段被过滤。

#### P3.4 单元测试

新增：

```text
agent-service/tests/core/test_parameter_resolver.py
```

覆盖：

- 初始 path 自动复用；
- MCP output 写回后自动复用；
- alias 映射；
- explicit user input override；
- LLM conflict 不覆盖高可信参数；
- missing required 检测；
- schema filter；
- compact context 排除 invalidated details。

## 10. Phase P4：DiagnosisAgent Phase 1 接入

### 10.1 目标

将 `DiagnosisAgent` 从薄 context dict 迁移到 `DiagnosisContext` + `ParameterResolver` 主路径，先完成上下文与参数复用闭环。

### 10.2 任务

#### P4.1 改造 `DiagnosisAgent.run`

目标文件：

- `agent-service/src/core/agents/diagnosis_agent.py`

改造点：

- 创建或恢复 `DiagnosisContext`；
- root_message、extracted、path 写入 known_params/provenance；
- playbook selection / query rewrite 使用 `context.compact_for_llm(stage="playbook_selection")`；
- search result 写入 context 与 evidence；
- playbook candidates 创建 CandidateSet 占位结构；
- initial step 参数解析改用 `ParameterResolver`；
- pending metadata 携带 `diagnosis_id/context_revision/pending_id/tool_schema_hash`。

验收：

- 首轮诊断创建 context；
- initial path 不重复询问；
- playbook search evidence 与 context 关联；
- 缺参 pending 可恢复到对应 diagnosis context。

#### P4.2 改造 `_execute_tool_and_check_next`

改造点：

- 签名接收 `DiagnosisContext` 或 `diagnosis_id`；
- 调 MCP 仍通过 `MCPGateway.execute_profiler_tool`；
- 执行后 `context.apply_step_result`；
- next step 参数解析使用 `ParameterResolver`；
- 自动推进递归改 loop；
- auto_count 与 total_auto_steps 写入 context；
- 每步写 audit event。

验收：

- 多步自动执行不丢 context；
- 每步 MCP output 可进入后续参数复用；
- 达到 per-turn auto limit 进入 pending；
- 不出现深递归。

#### P4.3 改造 `resume`

改造点：

- 通过 `diagnosis_id` 加载 context；
- 校验 `context_revision`；
- 恢复 pending state；
- 用户输入先交给后续 `PendingInputRouter`，Phase 1 可先对 `answer_pending` 做兼容；
- schema extraction 传 compact context。

验收：

- suspend/resume 后上下文不变薄；
- 用户只补一个参数时仍支持 fast path；
- LLM schema extraction 可使用 compact context。

#### P4.4 集成测试

新增/扩展：

```text
agent-service/tests/test_dynamic_mcp_orchestration.py
agent-service/tests/test_orchestrator_llm_assistance.py
```

覆盖：

- 初始输入 path 后 next step 自动复用；
- pending 补参后继续；
- MCP output 参数后续复用；
- LLM assistance failure 降级 deterministic。

## 11. Phase P5：PendingInputRouter 与 paused 多诊断

### 11.1 目标

pending 状态下不再把所有用户输入都当作参数；先识别用户是在回答、暂停、重启、取消、回退还是切换话题。

### 11.2 任务

#### P5.1 实现 PendingInputRouter

目标文件：

- `agent-service/src/core/diagnosis/pending_router.py`

接口：

```python
route(user_input, pending, contexts) -> PendingInputIntent
```

intent：

- `answer_pending`
- `modify_previous_step`
- `pause_diagnosis`
- `restart_diagnosis`
- `resume_paused`
- `cancel_diagnosis`
- `switch_topic_or_chat`
- `ask_status`
- `unclear`

验收规则：

- “重新分析 /data/new_trace” => restart；
- “不用继续了 / 暂停 / 等会再说” => pause；
- paused 不阻塞普通聊天/知识问答；
- 多 paused + 裸“继续” => 最新 created_at；
- 明确恢复但多匹配 => choice pending。

#### P5.2 接入 Orchestrator continue path

目标文件：

- `agent-service/src/core/orchestrator.py`

改造点：

- `continue_with_input` 不再直接把输入送入 `agent.resume`；
- 先加载 active pending 和 diagnosis contexts；
- 调 `PendingInputRouter`；
- 根据 intent 决定 answer/pause/restart/resume/switch_topic；
- Phase P7 后改为入队，当前可先同步执行。

验收：

- pending 中说“暂停”不会被解析成参数；
- pending 中说“重新分析 xxx”会重启而不是污染旧 pending；
- paused 后普通知识问答不影响 paused context。

#### P5.3 测试

新增：

```text
agent-service/tests/core/test_pending_input_router.py
```

覆盖 P0-1-R1 到 P0-1-R6。

## 12. Phase P6：InvalidationEngine 与 report guard

### 12.1 目标

支持用户回退历史步骤、修改已使用参数时的下游失效，确保旧 evidence 不污染当前报告。

### 12.2 任务

#### P6.1 实现 InvalidationEngine

目标文件：

- `agent-service/src/core/diagnosis/invalidation.py`

接口：

```python
invalidate_from_step(context, step_index, reason)
```

MVP 线性截断规则：

1. Step N 及之后 completed steps => invalidated；
2. produced_params 从 effective known_params 移除；
3. param_provenance 标记 invalidated；
4. CandidateSet from invalidated steps invalidated；
5. evidence ids 移到 invalidated_evidence_ids；
6. pending 若指向 invalidated step 则清理；
7. context revision + 1；
8. 写 audit event。

验收：

- Step 2 参数变化会使 Step 2+ invalidated；
- invalidated params 不进入 known_params；
- invalidated evidence 不进入 effective evidence。

#### P6.2 rollback / modify previous step intent

接入点：

- `PendingInputRouter`
- `Orchestrator.continue_with_input`
- `DiagnosisAgent.resume`

行为：

- 识别用户修改历史 step 参数；
- 计算影响范围；
- 发 confirmation pending，展示 invalidated steps impact；
- 用户确认后调用 `invalidate_from_step` 并从目标 step 重跑。

验收：

- 前端/后端都能看到失效影响；
- 用户未确认前不修改 context。

#### P6.3 实现 ReportEvidenceValidator

目标文件：

- `agent-service/src/core/diagnosis/report_guard.py`

接口：

```python
get_effective_evidence(context)
validate_current_report_evidence(context, evidence_ids)
```

校验：

- evidence_id 在 effective_evidence_ids；
- source step status == completed；
- evidence 不在 invalidated_evidence_ids；
- evidence 属于当前 diagnosis_id/path；
- evidence 与当前关键参数 revision 兼容。

验收：

- current_report 不引用 invalidated evidence；
- historical_report 必须带 disclaimer。

#### P6.4 测试

新增：

```text
agent-service/tests/core/test_diagnosis_invalidation.py
agent-service/tests/core/test_report_evidence_validator.py
```

覆盖：

- Step 2 回退失效 Step 2-5；
- produced params 移除；
- CandidateSet 失效；
- current_report 排除 invalidated evidence；
- historical_report 标记历史/失效。

## 13. Phase P7：OperationQueue 与幂等

### 13.1 目标

保证同一 session 内所有会修改 diagnosis context 的操作串行化，避免并发 MCP execution、rollback、resume、restart 导致状态污染。

### 13.2 任务

#### P7.1 实现 DiagnosisOperationQueue

目标文件：

- `agent-service/src/core/diagnosis/queue.py`

接口：

```python
enqueue_or_get_existing(operation)
process_next(session_id)
validate_operation_against_latest_context(operation, context)
```

规则：

- 每个 session 一个 mutation queue；
- 同一时间只运行一个 operation；
- 严格 FIFO；
- 执行前 stale 校验；
- stale/skipped 后继续处理队列。

验收：

- 并发 resume 只串行执行；
- stale operation 不污染最新 context；
- queue 状态可查询。

#### P7.2 幂等实现

要求：

- 前端传 `idempotency_key`；
- 后端按 `(session_id, idempotency_key)` 查重；
- 前端缺失时后端使用 `pending_id + normalized_user_input + short_time_window` 弱去重。

验收：

- 同一 key 重复提交只生成/执行一个 operation；
- 重复点击不会重复执行 MCP step。

#### P7.3 Orchestrator 接入 queue

目标文件：

- `agent-service/src/core/orchestrator.py`

改造：

- `continue_with_input` 创建 `DiagnosisOperation`；
- resume/restart/pause/rollback/generate_report 都入队；
- operation 状态通过 SSE 发送。

验收：

- 已有 mutation 运行时新 mutation 入队；
- FIFO；
- cancel/restart/rollback 不插队；
- 执行前 stale 检查。

#### P7.4 测试

新增：

```text
agent-service/tests/core/test_diagnosis_operation_queue.py
```

覆盖 P0-2-R1 到 P0-2-R5。

## 14. Phase P8：CandidateSet 生命周期

### 14.1 目标

支持 playbook、iteration、rank、operator、template、branch 等候选集的跨轮选择和稳定编号。

### 14.2 任务

#### P8.1 实现 CandidateSetManager

建议文件：

- `agent-service/src/core/diagnosis/candidates.py`

接口：

```python
create_candidate_set(type, candidates, source_step, primary=True)
resolve_selection(user_input, context)
select_candidate(candidate_set_id, global_index)
invalidate_by_source_step(step_index)
```

规则：

- 每个 context 最多一个 primary active CandidateSet；
- 新 primary active 出现时旧 primary active => superseded/selected；
- 来源 step invalidated => CandidateSet invalidated；
- “第二个”等序号默认绑定最近 active CandidateSet；
- 编号全局稳定，分页不重排；
- compact context 最多 20 个 active candidates。

验收：

- 用户说“第二个”可解析；
- CandidateSet 来源 step 失效后不可再选择；
- global index 稳定。

#### P8.2 接入 MCP search / execute result

接入点：

- playbook candidates from search；
- MCP result 中候选 output；
- branch playbook candidates。

验收：

- 多 playbook 选择创建 CandidateSet；
- iteration/rank/operator 候选创建 CandidateSet；
- candidate selected 写入 known_params/provenance。

#### P8.3 测试

新增：

```text
agent-service/tests/core/test_candidate_set.py
```

覆盖 P1-1-R1 到 P1-1-R4。

## 15. Phase P9：Schema drift / MCP reconciliation / playbook switch

### 15.1 目标

处理长时间 pending 后 schema 变化、MCP blocked/stale/context_changed，以及用户明确/模糊切换 playbook 的工业级边界场景。

### 15.2 任务

#### P9.1 Schema drift migration

接入点：

- `DiagnosisAgent.resume`
- `ParameterResolver`
- `MCPGateway.ensure_tools_loaded/search_profiler_tools`

行为：

1. pending 保存 `tool_name/tool_schema/tool_schema_hash/selected_playbook/step_index`；
2. resume 获取最新 schema；
3. schema hash 不一致 => drift；
4. 保留新 schema properties 中兼容旧参数；
5. obsolete args 不传 MCP，保留 audit；
6. 用 context/user_input 重新 resolve required；
7. 缺参再问用户。

验收：

- schema drift 自动迁移；
- obsolete args 不传 MCP；
- tool/playbook 不存在时 re-search。

#### P9.2 ReconciliationEngine

目标文件：

- `agent-service/src/core/diagnosis/reconciliation.py`

接口：

```python
reconcile(context, mcp_result, current_tool, args) -> ReconciliationResult
```

触发：

- MCP 返回 blocked；
- stale；
- context_changed；
- prerequisite_missing。

规则：

- MCP 是真相源；
- 可确定性修复且参数齐全 => 自动补执行 required step；
- 同一 blocked reason 最多自动修复 1 次；
- 同一 diagnosis 连续 reconciliation 最多 2 次；
- 重新执行历史步骤 => `invalidate_from_step`；
- 超限 => suspend/failed with explanation。

验收：

- MCP blocked 不被当普通失败直接终止；
- 可修复场景自动修复；
- 超限后可解释地暂停。

#### P9.3 Playbook switch

行为：

- 明确切换 playbook：旧 path superseded，旧 evidence audit only；
- 不自动迁移任何参数；
- 使用新用户输入重新 search；
- 模糊切换意图必须澄清。

验收：

- 旧 evidence 不进入当前报告；
- 不跨 playbook 自动迁移参数；
- 模糊 switch 不自动执行。

#### P9.4 测试

新增：

```text
agent-service/tests/core/test_schema_drift.py
agent-service/tests/core/test_diagnosis_reconciliation.py
agent-service/tests/core/test_playbook_switch.py
```

覆盖：

- schema drift 新 schema 迁移；
- obsolete args audit only；
- MCP blocked 自动补执行；
- reconciliation 上限；
- playbook switch supersede。

## 16. Phase P10：SSE/API 契约与前端 UI

### 16.1 目标

让用户能看到诊断上下文、参数来源、失效影响、队列状态、候选集和 paused diagnosis。

### 16.2 后端 SSE 任务

目标文件：

- `agent-service/src/api/routes/streaming.py`
- `agent-service/src/core/orchestrator.py`

新增事件：

- `diagnosis_context_updated`
- `diagnosis_step_invalidated`
- `diagnosis_rollback_detected`
- `diagnosis_auto_fill`
- `diagnosis_operation_queued`
- `diagnosis_operation_updated`
- `diagnosis_candidate_set_created`
- `diagnosis_candidate_selected`
- `diagnosis_reconciliation`
- `diagnosis_schema_drift`
- `diagnosis_audit_event`

扩展 `user_input_required`：

- `diagnosis_id`
- `context_revision`
- `known_context`
- `missing`
- `candidate_set_id`
- `impact.invalidated_steps`
- `reason`

验收：

- 前端可根据 SSE 构造 diagnosis panel；
- rollback confirmation 能显示影响；
- queue 状态可见。

### 16.3 前端类型与状态

目标文件：

- `agent-web/src/types/index.ts`
- `agent-web/src/stores/index.ts`
- `agent-web/src/services/api.ts`

新增类型：

- `DiagnosisContextSummary`
- `ParamProvenanceSummary`
- `DiagnosisOperationSummary`
- `CandidateSetView`
- `PausedDiagnosisSummary`
- `DiagnosisAuditEventView`

验收：

- SSE 事件有类型；
- store 保存 active diagnosis、queue、candidate set、paused list。

### 16.4 前端组件

建议新增：

- `DiagnosisContextPanel.tsx`
- `ParameterProvenancePanel.tsx`
- `DiagnosisOperationQueue.tsx`
- `PausedDiagnosisList.tsx`
- `CandidateSetPanel.tsx`
- `InvalidationImpactDialog.tsx`

验收：

- 展示诊断进度；
- 展示简化 provenance，可展开详情；
- 历史 step rerun/reselect 前展示失效影响并确认；
- queue 简化展示，可展开；
- paused diagnosis 支持继续、取消、查看；
- invalidated evidence 灰显。

## 17. Phase P11：可观测性与 metrics

### 17.1 目标

让诊断上下文机制可运营、可定位、可审计。

### 17.2 Audit 完整化

确保记录：

- param_added / param_updated / param_invalidated；
- step_started / step_completed / step_failed / step_invalidated；
- pending_created / pending_resolved / pending_paused；
- candidate_set_created / selected / invalidated；
- operation_queued / running / completed / stale；
- rollback_detected / applied；
- reconciliation_attempted / succeeded / failed；
- schema_drift_detected / schema_migrated；
- playbook_switched；
- report_generated。

验收：

- 所有关键状态变化有 audit event；
- audit event 持久化；
- 简化 timeline 可由 audit events 重建。

### 17.3 Metrics

目标文件：

- `agent-service/src/observability/metrics.py`
- 相关调用点

新增指标：

- `diagnosis_user_prompts_total`
- `diagnosis_auto_fill_success_total`
- `diagnosis_auto_fill_failed_total`
- `diagnosis_param_conflict_total`
- `diagnosis_rollback_total`
- `diagnosis_step_invalidated_total`
- `diagnosis_reconciliation_total`
- `diagnosis_reconciliation_failed_total`
- `diagnosis_operation_queued_total`
- `diagnosis_operation_stale_total`
- `diagnosis_operation_queue_length`
- `diagnosis_operation_wait_seconds`
- `diagnosis_candidate_set_created_total`
- `diagnosis_candidate_selected_total`
- `diagnosis_candidate_invalidated_total`
- `diagnosis_schema_drift_total`
- `diagnosis_schema_migration_success_total`
- `diagnosis_schema_migration_failed_total`
- `diagnosis_auto_steps_total`
- `diagnosis_auto_limit_hit_total`
- `diagnosis_report_generated_total`
- `diagnosis_report_invalidated_evidence_excluded_total`

验收：

- `/metrics` 可暴露；
- 指标不会包含敏感参数值或路径原文，必要时脱敏/计数。

## 18. Phase P12：集成测试、验收与文档收口

### 18.1 后端测试矩阵

| 模块 | 覆盖 |
| --- | --- |
| DiagnosisContext | 序列化、revision、provenance、pending、compact |
| ParameterResolver | 参数复用、alias、conflict、schema filter、LLM fallback |
| PendingInputRouter | pending/paused/restart/cancel/resume/unclear |
| InvalidationEngine | Step N+ 失效、params/evidence/candidate invalidation |
| OperationQueue | FIFO、idempotency、stale/skipped、并发 |
| CandidateSetManager | 全局编号、选择解析、source invalidation |
| SchemaDrift | 新 schema 迁移、obsolete audit、missing required |
| Reconciliation | blocked/stale 自动修复、上限、失败解释 |
| ReportEvidenceValidator | current vs historical evidence |
| Orchestrator | continue 入队、pending routing、resume context |
| Streaming API | 新 SSE 事件、user_input_required 扩展 |

### 18.2 端到端验收场景

1. 用户初始输入包含 path，后续 step 需要 path，系统自动补全且不重复询问。
2. MCP 前序输出 iteration/rank，后续 step 自动复用并展示 provenance。
3. pending 等待参数时，用户说“暂停”，诊断进入 paused，pending 保留。
4. 多个 paused diagnosis 时，裸“继续”恢复最近创建的 paused diagnosis。
5. 已执行 Step 1-5，用户修改 Step 2 参数，Step 2-5 invalidated，旧 evidence 不进入 current report。
6. 同一个 idempotency_key 重复提交，只创建/处理一个 operation。
7. MCP step 正在执行时另一个 mutation 到达，后者入队并按 FIFO 处理。
8. queued operation 执行前发现 context_revision 不适用，标记 stale/skipped。
9. CandidateSet 来源 step invalidated 后，用户再说“第二个”不可解析并提示原因。
10. pending schema drift 后使用新 schema 自动迁移，缺参数再问。
11. MCP blocked 且可确定修复时自动 reconciliation；超限后暂停并解释。
12. 当前报告只引用 effective evidence；historical report 明确标记历史/失效。
13. 前端展示 context panel、参数 provenance、queue、paused list、candidate set、invalidated evidence。

### 18.3 命令验收

后端：

```bash
cd agent-service
pytest tests/ -v
pytest tests/test_dynamic_mcp_orchestration.py tests/test_orchestrator_llm_assistance.py -v
```

前端：

```bash
cd agent-web
npm run lint
npm run build
```

MCP service 回归：

```bash
cd mcp_service_code/ms_mcp
python -m pytest tests/ -v
```

验收要求：

- 新增测试通过；
- 现有 dynamic MCP orchestration 测试不退化；
- frontend build 通过；
- MCP service 顶层 meta-tool 约束不被破坏。

### 18.4 文档更新

目标文件：

- `docs/diagnosis_context_requirements.md`
- `docs/diagnosis_context_design.md`
- `agent-service/README.md`
- `agent-web/README.md`
- `CLAUDE.md` 如新增重要命令或架构约束

内容：

- context persistence；
- pending/paused 恢复；
- rollback invalidation；
- operation queue；
- SSE events；
- frontend diagnosis panel；
- metrics/audit；
- known limitations。

## 19. 推荐提交切分

1. `docs: add diagnosis context implementation workflow`
2. `feat: add diagnosis context models`
3. `feat: persist diagnosis contexts and audit events`
4. `feat: add diagnosis parameter resolver`
5. `feat: pass compact diagnosis context to llm extraction`
6. `feat: integrate diagnosis context into diagnosis agent`
7. `feat: route pending diagnosis input before resume`
8. `feat: add diagnosis invalidation engine`
9. `feat: guard reports with effective diagnosis evidence`
10. `feat: add diagnosis operation queue and idempotency`
11. `feat: manage diagnosis candidate sets`
12. `feat: handle diagnosis schema drift`
13. `feat: reconcile mcp blocked diagnosis states`
14. `feat: support diagnosis playbook switching`
15. `feat: stream diagnosis context events`
16. `feat: render diagnosis context panel and queue`
17. `feat: add diagnosis audit metrics`
18. `test: cover diagnosis context workflows`
19. `docs: update diagnosis context operation guide`

## 20. 实施检查清单

### 模型与存储

- [ ] `agent-service/src/core/diagnosis/` 包已创建
- [ ] `DiagnosisContext` 模型完成
- [ ] `ParamProvenance` 模型完成
- [ ] `StepRecord` 模型完成
- [ ] `PendingStepState` 模型完成
- [ ] `CandidateSet` / `CandidateItem` 模型完成
- [ ] `DiagnosisOperation` 模型完成
- [ ] `DiagnosisAuditEvent` 模型完成
- [ ] `diagnosis_contexts` 表完成
- [ ] `diagnosis_operations` 表完成
- [ ] `diagnosis_audit_events` 表完成
- [ ] Store CRUD 方法完成

### 参数复用与 LLM compact context

- [ ] `compact_for_llm` 完成
- [ ] invalidated details 默认排除
- [ ] latest 3 completed steps 规则完成
- [ ] active CandidateSet max 20 规则完成
- [ ] `ParameterResolver` 完成
- [ ] alias map 完成
- [ ] conflict handling 完成
- [ ] schema filter 完成
- [ ] `extract_parameters_by_schema(..., context=None)` 完成

### DiagnosisAgent 接入

- [ ] `run()` 创建/恢复 context
- [ ] playbook selection 使用 compact context
- [ ] search evidence 写入 context
- [ ] initial step 使用 ParameterResolver
- [ ] pending metadata 携带 diagnosis_id/context_revision
- [ ] `_execute_tool_and_check_next` 使用 context
- [ ] 自动推进改 loop
- [ ] MCP output 写回 context
- [ ] `resume()` 加载 context
- [ ] suspend/resume 不再使用薄 context

### Pending / Paused

- [ ] `PendingInputRouter` 完成
- [ ] pending 中 restart 识别完成
- [ ] pending 中 pause 识别完成
- [ ] paused 不阻塞普通聊天/知识问答
- [ ] 多 paused 裸继续恢复最新
- [ ] 明确恢复多匹配时询问选择

### 失效与报告

- [ ] `InvalidationEngine` 完成
- [ ] Step N+ 线性失效完成
- [ ] produced params invalidation 完成
- [ ] evidence effective/invalidated 完成
- [ ] rollback confirmation impact 完成
- [ ] `ReportEvidenceValidator` 完成
- [ ] current_report 排除 invalidated evidence
- [ ] historical_report disclaimer 完成

### OperationQueue

- [ ] session-level mutation queue 完成
- [ ] FIFO 完成
- [ ] idempotency_key 查重完成
- [ ] 弱去重完成
- [ ] stale/skipped 校验完成
- [ ] operation SSE 事件完成

### CandidateSet

- [ ] `CandidateSetManager` 完成
- [ ] primary active 唯一完成
- [ ] global stable index 完成
- [ ] ordinal selection 完成
- [ ] source step invalidation 完成
- [ ] compact candidate limit 完成

### Schema / Reconciliation / Switch

- [ ] pending schema hash 保存完成
- [ ] resume schema drift 检测完成
- [ ] latest schema migration 完成
- [ ] obsolete args audit only 完成
- [ ] tool/playbook missing re-search 完成
- [ ] `ReconciliationEngine` 完成
- [ ] blocked/stale/context_changed 处理完成
- [ ] reconciliation 上限完成
- [ ] playbook switch supersede 完成
- [ ] 模糊 switch clarification 完成

### SSE / 前端

- [ ] `diagnosis_context_updated` 完成
- [ ] `diagnosis_step_invalidated` 完成
- [ ] `diagnosis_auto_fill` 完成
- [ ] `diagnosis_operation_queued/updated` 完成
- [ ] `diagnosis_candidate_set_created/selected` 完成
- [ ] `diagnosis_reconciliation` 完成
- [ ] `diagnosis_schema_drift` 完成
- [ ] `user_input_required` 扩展完成
- [ ] `DiagnosisContextPanel` 完成
- [ ] `ParameterProvenancePanel` 完成
- [ ] `DiagnosisOperationQueue` 完成
- [ ] `PausedDiagnosisList` 完成
- [ ] `CandidateSetPanel` 完成
- [ ] `InvalidationImpactDialog` 完成

### Observability / Tests

- [ ] audit event persistence 完成
- [ ] metrics 完成
- [ ] simplified timeline 完成
- [ ] 后端单测通过
- [ ] 后端集成测试通过
- [ ] 前端 lint/build 通过
- [ ] MCP service 回归通过
- [ ] 端到端验收场景通过

## 21. 关键风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| DiagnosisContext 与 MCP Context Board 双状态冲突 | 执行状态不一致 | 明确 MCP 为执行状态真相源；agent-service 只做交互与上下文；blocked/stale 进入 reconciliation |
| 参数复用错误导致误执行 | 诊断结论错误 | provenance + confidence + schema validation + conflict handling；关键冲突确认 |
| LLM 抽取覆盖有效参数 | 上下文污染 | LLM 只建议；Resolver 决定；高可信 known params 不被 LLM 覆盖 |
| 回退未失效 downstream evidence | current report 污染 | InvalidationEngine + ReportEvidenceValidator 双保险 |
| OperationQueue 引入死锁或长等待 | 用户体验下降 | 每 operation 状态可见；metrics 监控 wait_seconds；超时/失败释放锁 |
| schema drift 兼容不完整 | resume 失败 | 新 schema 优先；obsolete audit only；缺参再问；tool missing re-search |
| CandidateSet 序号错乱 | 用户选择错误候选 | global stable index；来源失效后禁止解析；前端展示全局编号 |
| SSE 事件过多 | 前端复杂度上升 | context_updated 做摘要；详情按需展开；audit_event 可配置采样或仅调试展示 |
| 一次性改造范围过大 | 难以回滚 | 按 phase 提交，每 phase 有独立测试和 feature flag/兼容 fallback |

## 22. 第一版完成定义

第一版完成需满足：

1. 每个 diagnosis 有独立 `diagnosis_id` 和持久化 `DiagnosisContext`。
2. 初始用户输入和 MCP 输出中的有效参数可在后续 step 自动复用。
3. suspend/resume 后不丢失上下文。
4. pending 下用户输入先经过 intent routing，不再直接作为参数。
5. 用户暂停后可恢复；同 session 支持多个 paused diagnosis。
6. 用户修改历史 Step N 参数时，Step N 及之后结果、参数、evidence、CandidateSet 失效。
7. current report 只使用 effective evidence。
8. 同 session mutation 串行化，重复提交幂等。
9. CandidateSet 支持全局稳定编号和来源失效。
10. schema drift resume 时可迁移或重新询问。
11. MCP blocked/stale 可进入 reconciliation，且有自动修复上限。
12. 前端可展示 diagnosis progress、参数来源、queue、paused list、candidate set、失效影响。
13. audit events 和 metrics 可用于定位重复询问、参数冲突、rollback、queue wait、schema drift 等问题。
14. 所有新增后端单测、关键集成测试、前端 build 通过。

# DiagnosisAgent 工业级上下文机制系统设计

## 1. 设计范围

本文档基于 `docs/diagnosis_context_requirements.md`，定义 `DiagnosisAgent` 的工业级上下文、参数复用、回退失效、operation queue、CandidateSet、schema drift、report evidence 校验、前端事件和可观测性设计。

设计遵循现有架构约束：

- profiling 执行必须通过 `MCPGateway` 调用 `search_profiler_tools` / `execute_profiler_tool`；
- MCP service 是 playbook 执行状态和前置依赖的真相源；
- agent-service 负责会话上下文、用户交互、LLM compact context、报告 effective evidence 和前端状态表达。

## 2. 总体架构

```text
┌───────────────────────────────────────────────────────────────┐
│                         agent-web                             │
│ Diagnosis Panel / Candidate UI / Queue UI / Paused List        │
└───────────────────────────────┬───────────────────────────────┘
                                │ HTTP + SSE
┌───────────────────────────────▼───────────────────────────────┐
│                         Orchestrator                          │
│ handle_message / continue_with_input / SSE events              │
└───────────────────────────────┬───────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────┐
│                        DiagnosisAgent                         │
│ search / execute / suspend / resume / pause / restart          │
└───────┬───────────────┬───────────────┬───────────────┬───────┘
        │               │               │               │
        ▼               ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│DiagnosisCtx │ │ParamResolver │ │Invalidation  │ │OperationQueue│
│             │ │              │ │Engine        │ │              │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│CandidateSet │ │Reconciliation│ │ReportEvidence│ │Audit/Metrics │
│Manager      │ │Engine        │ │Validator     │ │              │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │                │
       └────────────────┴────────┬───────┴────────────────┘
                                 ▼
┌───────────────────────────────────────────────────────────────┐
│                         SessionStore                          │
│ diagnosis_contexts / operations / audit_events / evidence      │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                          MCPGateway                           │
│ search_profiler_tools / execute_profiler_tool                  │
└───────────────────────────────────────────────────────────────┘
```

## 3. 模块设计

建议新增包：

```text
agent-service/src/core/diagnosis/
├── __init__.py
├── context.py              # DiagnosisContext and serialization
├── models.py               # ParamProvenance, StepRecord, CandidateSet, Operation
├── resolver.py             # ParameterResolver
├── invalidation.py         # InvalidationEngine and rollback handling
├── pending_router.py       # PendingInputRouter
├── queue.py                # DiagnosisOperationQueue
├── reconciliation.py       # MCP blocked/stale reconciliation
├── report_guard.py         # ReportEvidenceValidator
├── audit.py                # DiagnosisAuditEvent writer
└── compact.py              # compact_for_llm helpers if split from context
```

`DiagnosisAgent` 应变薄，负责流程编排，不再手写散落的 context dict。

## 4. 数据模型

### 4.1 DiagnosisContext

```python
class DiagnosisContext:
    diagnosis_id: str
    session_id: str
    plan_id: str | None
    root_message: str
    latest_user_input: str | None

    status: str  # active | paused | completed | cancelled | superseded | failed
    selected_playbook: str | None
    playbook_name: str | None

    current_step_index: int | None
    current_tool_name: str | None

    known_params: dict[str, Any]
    param_provenance: dict[str, ParamProvenance]

    completed_steps: list[StepRecord]
    invalidated_steps: list[StepRecord]

    candidate_sets: list[CandidateSet]
    primary_candidate_set_id: str | None

    pending: PendingStepState | None
    operation_queue_snapshot: list[str]

    effective_evidence_ids: list[str]
    invalidated_evidence_ids: list[str]

    total_auto_steps: int
    reconciliation_state: ReconciliationState
    revision: int
    created_at: str
    updated_at: str
```

### 4.2 ParamProvenance

```python
class ParamProvenance:
    key: str
    source: str  # user_initial | user_resume | user_selection | mcp_output | mcp_suggested_argument | blackboard_extracted | llm_extraction | transferred | system_default
    confidence: str  # high | medium | low
    source_step_index: int | None
    source_tool_name: str | None
    source_evidence_id: str | None
    user_confirmed: bool
    revision_created: int
    revision_invalidated: int | None
    invalidated: bool
```

### 4.3 StepRecord

```python
class StepRecord:
    step_id: str
    step_index: int
    tool_name: str
    arguments: dict[str, Any]
    argument_sources: dict[str, str]
    result_summary: dict[str, Any]
    evidence_id: str | None
    next_step: dict[str, Any] | None

    status: str  # completed | failed | invalidated | superseded
    produced_params: list[str]
    depends_on_params: list[str]

    revision_created: int
    revision_invalidated: int | None
    invalidation_reason: str | None
```

### 4.4 PendingStepState

```python
class PendingStepState:
    pending_id: str
    resume_action: str
    tool_name: str | None
    tool_schema: dict[str, Any] | None
    tool_schema_hash: str | None
    resolved_arguments: dict[str, Any]
    required_missing: list[str]
    auto_step_count: int
    reason: str
    candidate_set_id: str | None
    created_revision: int
```

### 4.5 CandidateSet

```python
class CandidateSet:
    candidate_set_id: str
    type: str  # playbook | iteration | rank | operator | template | branch | other
    source_step_index: int | None
    source_tool_name: str | None
    source_evidence_id: str | None
    status: str  # active | selected | expired | invalidated | superseded
    candidates: list[CandidateItem]
    selected_value: Any | None
    created_revision: int
    invalidated_revision: int | None
```

```python
class CandidateItem:
    global_index: int
    value: Any
    label: str
    description: str | None
    metadata: dict[str, Any]
```

### 4.6 DiagnosisOperation

```python
class DiagnosisOperation:
    operation_id: str
    idempotency_key: str | None
    session_id: str
    diagnosis_id: str | None
    type: str  # answer_pending | rollback | pause | restart | resume_paused | cancel | switch_playbook | generate_report
    payload: dict[str, Any]
    status: str  # queued | running | completed | failed | stale | skipped | cancelled
    target_pending_id: str | None
    expected_revision: int | None
    created_at: str
    started_at: str | None
    completed_at: str | None
```

### 4.7 DiagnosisAuditEvent

```python
class DiagnosisAuditEvent:
    id: str
    session_id: str
    diagnosis_id: str | None
    event_type: str
    revision: int | None
    payload: dict[str, Any]
    created_at: str
```

## 5. 持久化设计

建议在 `SessionStore` 增加 JSON blob 起步：

```text
diagnosis_contexts
- diagnosis_id TEXT PRIMARY KEY
- session_id TEXT NOT NULL
- status TEXT NOT NULL
- context_json TEXT NOT NULL
- revision INTEGER NOT NULL
- created_at TEXT NOT NULL
- updated_at TEXT NOT NULL
```

```text
diagnosis_operations
- operation_id TEXT PRIMARY KEY
- session_id TEXT NOT NULL
- diagnosis_id TEXT
- idempotency_key TEXT
- type TEXT NOT NULL
- status TEXT NOT NULL
- payload_json TEXT NOT NULL
- target_pending_id TEXT
- expected_revision INTEGER
- created_at TEXT NOT NULL
- started_at TEXT
- completed_at TEXT
```

```text
diagnosis_audit_events
- id TEXT PRIMARY KEY
- session_id TEXT NOT NULL
- diagnosis_id TEXT
- event_type TEXT NOT NULL
- revision INTEGER
- payload_json TEXT NOT NULL
- created_at TEXT NOT NULL
```

索引：

```text
idx_diagnosis_contexts_session_status(session_id, status)
idx_diagnosis_operations_session_status(session_id, status)
idx_diagnosis_audit_session_diag(session_id, diagnosis_id, created_at)
unique(session_id, idempotency_key) where idempotency_key is not null
```

## 6. 核心流程设计

## 6.1 初始诊断

```text
handle_message
  ↓
IntentRouter => DIAGNOSIS / PROFILING_ANALYSIS
  ↓
DiagnosisAgent.run
  ↓
DiagnosisContext.create(status=active)
  ↓
MCPGateway.ensure_tools_loaded
  ↓
LLM playbook selection / query rewrite with context.compact_for_llm
  ↓
search_profiler_tools
  ↓
context records selected_playbook/search evidence
  ↓
ParameterResolver.resolve(initial_step)
  ↓
missing? create pending : execute step
```

## 6.2 参数解析

`ParameterResolver.resolve_for_step(...)` 顺序：

```text
1. start from suggested/existing args
2. schema filter
3. fill from current user explicit input
4. fill from context.known_params + alias map
5. fill from latest MCP output summary
6. fill query/message fields
7. LLM extraction with compact context
8. schema/candidate validation
9. conflict handling
10. missing required check
```

返回：

```python
class ParameterResolutionResult:
    arguments: dict[str, Any]
    missing_required: list[str]
    filled: list[ResolvedParameter]
    conflicts: list[ParameterConflict]
    needs_confirmation: bool
    question_reason: str | None
```

## 6.3 MCP step 执行

```text
execute step
  ↓
policy decide_before_mcp_execution  # 当前阶段只做 auto step limit，不做 tool risk
  ↓
execute_profiler_tool
  ↓
if MCP blocked/stale => ReconciliationEngine
  ↓
save evidence
  ↓
context.apply_step_result
  ↓
policy decide_after_mcp_result
  ↓
continue_auto? resolve next step
  ↓
missing? suspend : recurse/loop
```

建议将当前递归改为 loop，避免深递归：

```python
while next_step and auto_count < max_auto_steps_per_turn:
    ...
```

## 6.4 自动执行上限

配置：

```yaml
diagnosis:
  auto_execution:
    max_auto_steps_per_turn: 5
    max_auto_steps_per_diagnosis: 20
```

达到 per-turn 5 步：

```text
create pending resume_action=continue_after_auto_limit
question includes progress summary and next-step preview
```

用户确认继续：

```text
per-turn auto_count reset
total_auto_steps remains cumulative
```

达到 diagnosis 总 20 步：暂停并提示检查 playbook 或明确继续。

## 7. PendingInputRouter 设计

```python
class PendingInputRouter:
    async def route(
        self,
        user_input: str,
        pending: PendingInput | None,
        contexts: list[DiagnosisContext],
    ) -> PendingInputIntent:
        ...
```

Intent：

```text
answer_pending
modify_previous_step
pause_diagnosis
restart_diagnosis
resume_paused
cancel_diagnosis
switch_topic_or_chat
ask_status
unclear
```

规则：

- “重新分析 / 换一个 trace / 从头来” => restart。
- “暂停 / 等会再说 / 不用继续了” => pause。
- paused 状态下普通知识问题走 chat/knowledge，不影响 paused context。
- 多 paused + 裸“继续” => created_at 最新。
- 明确恢复但多匹配 => ask choice。

## 8. OperationQueue 设计

### 8.1 串行化

每个 session 一个 mutation queue，同一时间只运行一个 operation。

```python
async def enqueue_or_get_existing(operation): ...
async def process_next(session_id): ...
```

### 8.2 FIFO 与 stale 校验

严格 FIFO。每个 operation 执行前调用：

```python
validate_operation_against_latest_context(operation, context)
```

校验失败：

```text
operation.status = stale/skipped
write audit event
process next
```

### 8.3 幂等

- 前端传 `idempotency_key`。
- 后端唯一约束 `(session_id, idempotency_key)`。
- 前端缺失时，后端弱去重：`pending_id + normalized_user_input + short_time_window`。

## 9. InvalidationEngine 设计

### 9.1 线性截断 MVP

```python
invalidate_from_step(context, step_index, reason)
```

规则：

```text
1. Step N 及之后 completed steps => invalidated
2. produced_params from invalidated steps removed from effective known_params
3. param_provenance marked invalidated
4. candidate sets from invalidated steps invalidated
5. evidence ids moved to invalidated_evidence_ids
6. pending cleared if it targets invalidated step
7. context revision + 1
8. audit events written
```

### 9.2 参数冲突处理

```text
if conflict only affects unexecuted pending:
    override pending args
else:
    find provenance source_step_index
    invalidate_from_step(source_step_index)
```

LLM conflict without explicit modification intent => clarification pending。

## 10. ReconciliationEngine 设计

触发：MCP 返回 blocked/stale/context_changed/prerequisite_missing。

```python
class ReconciliationEngine:
    async def reconcile(context, mcp_result, current_tool, args) -> ReconciliationResult:
        ...
```

规则：

- MCP 是状态真相源。
- 可确定性修复且参数齐全 => 自动补执行 required step。
- 同一 blocked reason 最多自动修复 1 次。
- 同一 diagnosis 连续 reconciliation 最多 2 次。
- 重新执行历史步骤 => 调用 `invalidate_from_step`。
- 超限 => suspend/failed with explanation。

## 11. Schema Drift 设计

Pending 保存：

```text
tool_name
tool_schema
tool_schema_hash
selected_playbook
step_index
```

resume 时：

```text
1. 获取最新 schema，如果可用
2. 比较 schema_hash
3. 不一致 => schema drift
4. 保留新 schema properties 中兼容旧参数
5. obsolete args 不传 MCP，保留 audit
6. 用 context/user_input 重新 resolve required
7. 缺参再问用户
```

若 tool/playbook 不存在：

```text
重新 search playbook using root_message + known params
旧 path stale/superseded
新 path 重新开始
```

## 12. Playbook Switch 设计

明确切换 playbook：

```text
1. 当前 effective path => superseded
2. 旧 evidence audit only
3. 不自动迁移任何参数
4. 使用新用户输入重新 search_profiler_tools
5. 创建新的 effective diagnosis path/context 或在原 context 中创建新 path revision
```

模糊表达：询问澄清。

## 13. CandidateSetManager 设计

创建候选集：

```python
create_candidate_set(type, candidates, source_step, primary=True)
```

规则：

- 每个 context 最多一个 primary active CandidateSet。
- 新 primary active 出现时，旧 primary active => superseded/selected。
- 来源 step invalidated => CandidateSet invalidated。
- 序号按全局稳定编号解析。
- compact context 最多包含 20 个 active candidates；可先 deterministic filter。

## 14. ReportEvidenceValidator 设计

生成 current_report 前：

```python
effective = validator.get_effective_evidence(context)
```

校验：

- evidence_id 在 context.effective_evidence_ids；
- source step status == completed；
- evidence 不在 invalidated_evidence_ids；
- evidence 属于当前 diagnosis_id/path；
- evidence 与当前关键参数 revision 兼容。

historical_report：

- 可使用 invalidated evidence；
- 必须带 disclaimer；
- 明确失效原因和历史参数。

## 15. compact_for_llm 设计

默认输出：

```json
{
  "user_goal": "...",
  "selected_playbook": "...",
  "current_tool": "...",
  "known_params": {...},
  "param_sources": {...},
  "latest_completed_steps": ["last 3 summaries"],
  "last_mcp_result_summary": {...},
  "active_candidate_set": {"max_candidates": 20},
  "pending": {...},
  "invalidated_summary": ["minimal only"]
}
```

默认排除：

- invalidated step details；
- raw MCP result；
- all historical messages；
- all paused contexts；
- large candidate lists；
- obsolete schema args as active context。

## 16. LLM assistant 接口调整

`MCPLLMOrchestrationAssistant.extract_parameters_by_schema` 从：

```python
extract_parameters_by_schema(user_input, tool_schema, existing_args)
```

改为：

```python
extract_parameters_by_schema(
    user_input: str,
    tool_schema: dict,
    existing_args: dict,
    context: dict | None = None,
) -> dict
```

要求：

- 只输出 schema properties 内字段；
- 不使用 invalidated context；
- 不覆盖 existing_args，除非用户明确修改；
- 冲突由 resolver 处理，不由 LLM 直接决定状态变更。

## 17. SSE / 前端契约

建议新增事件：

```text
diagnosis_context_updated
diagnosis_step_invalidated
diagnosis_rollback_detected
diagnosis_auto_fill
diagnosis_operation_queued
diagnosis_operation_updated
diagnosis_candidate_set_created
diagnosis_candidate_selected
diagnosis_reconciliation
diagnosis_schema_drift
diagnosis_audit_event
```

`user_input_required` 扩展：

```json
{
  "input_type": "params|choice|confirmation|continue_confirmation",
  "question": "...",
  "reason": "missing_required_arguments|max_auto_steps_reached|schema_drift|clarification",
  "diagnosis_id": "diag_xxx",
  "context_revision": 8,
  "known_context": {...},
  "missing": [...],
  "candidate_set_id": "cset_xxx",
  "impact": {
    "invalidated_steps": [2,3,4]
  }
}
```

前端组件：

- Diagnosis Context / Progress Panel；
- parameter provenance 展示；
- step rerun/reselect action with impact confirmation；
- operation queue summary + expandable details；
- paused diagnoses list with resume/cancel/view；
- invalidated evidence 灰显；
- CandidateSet 全局编号展示。

## 18. Audit 与 Metrics

### 18.1 Audit event types

```text
param_added
param_updated
param_invalidated
step_started
step_completed
step_failed
step_invalidated
pending_created
pending_resolved
pending_paused
candidate_set_created
candidate_set_selected
candidate_set_invalidated
operation_queued
operation_running
operation_completed
operation_stale
rollback_detected
rollback_applied
reconciliation_attempted
reconciliation_succeeded
reconciliation_failed
schema_drift_detected
schema_migrated
playbook_switched
report_generated
```

### 18.2 Metrics

建议新增：

```text
diagnosis_user_prompts_total
diagnosis_auto_fill_success_total
diagnosis_auto_fill_failed_total
diagnosis_param_conflict_total
diagnosis_rollback_total
diagnosis_step_invalidated_total
diagnosis_reconciliation_total
diagnosis_reconciliation_failed_total
diagnosis_operation_queued_total
diagnosis_operation_stale_total
diagnosis_operation_queue_length
diagnosis_operation_wait_seconds
diagnosis_candidate_set_created_total
diagnosis_candidate_selected_total
diagnosis_candidate_invalidated_total
diagnosis_schema_drift_total
diagnosis_schema_migration_success_total
diagnosis_schema_migration_failed_total
diagnosis_auto_steps_total
diagnosis_auto_limit_hit_total
diagnosis_report_generated_total
diagnosis_report_invalidated_evidence_excluded_total
```

## 19. 与现有代码集成点

### 19.1 `DiagnosisAgent.run`

当前从 `blackboard.get("extracted", {})` 构造薄 context。应改为：

```python
context = diagnosis_context_store.create_or_start(...)
```

LLM selection/rewrite 使用：

```python
context.compact_for_llm(stage="playbook_selection")
```

### 19.2 `_resolve_step_arguments`

保留为兼容 helper，但主逻辑迁移到 `ParameterResolver`。

### 19.3 `_execute_tool_and_check_next`

签名改为使用 `DiagnosisContext`。执行后调用 `context.apply_step_result`，并使用 `ParameterResolver` 解析 next step。

### 19.4 `resume`

先恢复 `DiagnosisContext`，再调用 `PendingInputRouter`。不要直接将用户输入送入 schema extraction。

### 19.5 `Orchestrator.continue_with_input`

如果存在 active/paused pending，应创建 `DiagnosisOperation` 并入队，而不是直接调用 `agent.resume`。

## 20. 测试策略

新增测试：

```text
agent-service/tests/core/test_diagnosis_context.py
agent-service/tests/core/test_parameter_resolver.py
agent-service/tests/core/test_diagnosis_invalidation.py
agent-service/tests/core/test_diagnosis_operation_queue.py
agent-service/tests/core/test_candidate_set.py
agent-service/tests/core/test_schema_drift.py
agent-service/tests/core/test_report_evidence_validator.py
```

关键用例：

- path 从初始输入自动复用；
- MCP output 参数写回并复用；
- suspend/resume 保持 context；
- 用户回退 Step 2 使 Step 2+ invalidated；
- invalidated evidence 不进入 current_report；
- 多 paused diagnosis 裸继续恢复最新 created；
- idempotency key 重复提交只创建一个 operation；
- queued operation stale 自动跳过；
- CandidateSet 来源 step invalidated 后不可解析“第二个”；
- schema drift 使用新 schema 自动迁移；
- compact context 排除 invalidated details，包含最近 3 步和最多 20 candidates。

## 21. 分阶段实施建议

### Phase 1：上下文与参数复用

- `DiagnosisContext` JSON blob；
- `ParameterResolver`；
- compact context；
- pending metadata 携带 diagnosis_id/context_revision；
- LLM assistant context-aware schema extraction。

### Phase 2：失效与报告 guard

- `InvalidationEngine`；
- rollback intent；
- effective/invalidated evidence；
- `ReportEvidenceValidator`；
- historical_report 标记。

### Phase 3：队列、paused、多 CandidateSet

- `DiagnosisOperationQueue`；
- idempotency；
- multiple paused contexts；
- `CandidateSetManager`。

### Phase 4：MCP reconciliation / schema drift / playbook switch

- `ReconciliationEngine`；
- schema drift migration；
- playbook re-search migration；
- playbook switch clarification。

### Phase 5：前端和可观测性

- Diagnosis Panel；
- queue UI；
- paused list；
- audit event persistence；
- metrics；
- simplified replay timeline。

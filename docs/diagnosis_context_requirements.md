# DiagnosisAgent 工业级上下文机制需求规格

## 1. 背景

当前 `DiagnosisAgent` 在 MCP playbook 多步骤执行中存在以下问题：

- 每个 MCP step 容易重复询问用户已提供或已由 MCP 产出的参数。
- LLM 参数抽取只获得局部上下文，缺少完整诊断链路状态。
- `suspend/resume` 后上下文容易变薄或丢失。
- 用户回退修改历史步骤参数时，旧参数、旧 evidence、旧结论可能污染新诊断。
- session 下 evidence、pending、MCP Context Board、agent-service 上下文之间缺少统一一致性规则。

本需求定义 `DiagnosisAgent` 的工业级会话上下文、参数复用、回退失效、并发幂等、报告 evidence 校验、前端展示和可观测性能力。

## 2. 目标

1. 在一次诊断任务中持续维护结构化 `DiagnosisContext`。
2. 优先复用有效上下文和 MCP 输出，减少重复询问。
3. 支持 `pending`、`paused`、多个 paused diagnosis 和恢复。
4. 支持用户回退、历史步骤重选参数和下游失效。
5. 保证当前报告只使用有效 evidence。
6. 避免 LLM 推断、schema drift、并发提交导致上下文污染。
7. 保持 MCP service 作为 playbook 执行状态和依赖约束的真相源。
8. 提供工业级前端可见性、审计事件、metrics 和未来 replay 能力。

## 3. 非目标

当前阶段明确不做：

- MCP internal tool 的风险等级分类与按 tool 风险确认。
- 绕过 MCP meta-tools 直接调用 MCP internal tools。
- 完整 DAG 依赖级失效的第一阶段实现；第一阶段可采用线性截断。
- 完整诊断 replay 的 MVP 实现；MVP 可先做简化 timeline。

## 4. 核心原则

### 4.1 MCP 是执行状态真相源

MCP service 对 playbook 执行状态、前置依赖、step progress、blocked/stale/context_changed 判断拥有最高优先级。

agent-service 的 `DiagnosisContext` 负责：

- 用户交互上下文；
- 参数复用；
- LLM compact context；
- suspend/resume；
- 回退失效；
- 报告 effective evidence；
- 前端状态展示和审计。

当 MCP 与 agent-service 状态冲突时，agent-service 必须以 MCP 返回状态为准进行 reconciliation。

### 4.2 有效上下文可复用，失效上下文不可用

有效参数、有效 step、有效 evidence 可用于后续参数补全、LLM compact context 和当前报告。失效内容只能用于审计、历史查看、历史报告，不得进入当前诊断推理。

### 4.3 用户显式新意图优先，但必须保证一致性

用户显式提供的新参数可覆盖旧值，但如果旧值已被历史步骤/evidence 使用，必须触发回退/失效，而不是静默覆盖并继续执行。

## 5. 功能需求

## 5.1 DiagnosisContext

### FR-1：系统必须维护诊断级上下文

每个诊断任务必须拥有独立 `diagnosis_id` 和 `DiagnosisContext`，至少包含：

- `session_id`；
- `diagnosis_id`；
- 原始用户目标；
- 最新用户输入；
- selected playbook；
- 当前 step / tool；
- effective known params；
- param provenance；
- completed steps；
- invalidated steps；
- active / paused / cancelled / superseded 状态；
- pending state；
- CandidateSet；
- operation queue 状态；
- effective evidence ids；
- context revision。

### FR-2：每次 MCP step 后必须更新上下文

每次 `execute_profiler_tool` 成功后，系统应写入：

- step record；
- tool arguments；
- result summary；
- evidence id；
- next step；
- produced params；
- param provenance；
- CandidateSet，如果 MCP 返回候选；
- audit event。

### FR-3：suspend/resume 必须携带完整上下文

挂起时 pending metadata 或 session store 必须保存 `diagnosis_id`、`context_revision`、pending tool/schema/args、required missing 和 serialized context reference。

resume 时不得只恢复薄 context，必须恢复对应 `DiagnosisContext`。

## 5.2 Pending / Paused 输入意图

### FR-4：pending 状态下必须先路由用户输入意图

存在 active pending 时，用户输入不得直接作为 pending answer。必须先识别：

- `answer_pending`；
- `modify_previous_step`；
- `pause_diagnosis`；
- `restart_diagnosis`；
- `cancel_diagnosis`；
- `switch_topic_or_chat`；
- `ask_status`；
- `unclear`。

### 已确认规则

- **P0-1-R1**：pending 状态下用户说“重新分析 /data/new_trace”等，视为重启诊断，当前 pending 不作为参数处理。
- **P0-1-R2**：pending 状态下用户说“不用继续了 / 暂停 / 等会再说”，进入 paused；不清理 pending，不失效上下文。
- **P0-1-R3**：paused diagnosis 不阻塞普通聊天/知识问答；之后用户可说“继续”恢复。
- **P0-1-R4**：一个 session 内允许多个 paused diagnosis contexts。
- **P0-1-R5**：多个 paused diagnosis 并存时，裸“继续”默认恢复 created_at 最新的 paused diagnosis。
- **P0-1-R6**：明确恢复意图存在多匹配时，必须询问用户选择目标 diagnosis context。

## 5.3 并发、队列与幂等

### FR-5：session 内 diagnosis mutation 必须串行化

同一个 session 内，所有修改 diagnosis context 的操作必须串行处理，包括：resume、MCP execute、rollback、pause、restart、context update、report generation。

### FR-6：必须支持 operation queue

当 session 中已有 diagnosis mutation 正在执行时，新 mutation 必须进入 FIFO 队列。

### 已确认规则

- **P0-2-R1**：同一个 session 内，所有会修改 `DiagnosisContext` 的操作必须串行化。
- **P0-2-R2**：支持 FIFO operation queue；锁被占用时新 mutation 入队。
- **P0-2-R3**：队列严格 FIFO；cancel/restart/rollback 不覆盖前面已排队操作。
- **P0-2-R4**：queued operation 执行前必须重新校验上下文；不适用则 stale/skipped 并继续处理队列。
- **P0-2-R5**：前端 `idempotency_key` 为主，后端使用 pending_id + normalized input + 短时间窗口弱去重兜底。

## 5.4 MCP reconciliation

### FR-7：MCP blocked/stale 必须触发 reconciliation

当 MCP 返回 blocked、stale、context_changed、prerequisite_missing 等状态时，agent-service 必须停止当前自动链路并进入 reconciliation。

### 已确认规则

- **P0-3-R1**：MCP service 对 playbook 执行状态拥有最高优先级。
- **P0-3-R2**：MCP blocked 若可确定性修复，且所需参数已满足，则自动 reconciliation，不询问用户。
- **P0-3-R3**：自动 reconciliation 有上限：同一 blocked reason 最多 1 次；同一 diagnosis 连续自动 reconciliation 最多 2 次。
- **P0-3-R4**：MCP reconciliation 重执行历史步骤时，触发与用户 rollback 相同的下游失效机制。

## 5.5 Report evidence 有效性

### FR-8：当前报告只能使用 effective evidence

报告生成必须使用当前 `DiagnosisContext` 中有效步骤关联的 evidence，不能默认使用 session 下全部 evidence。

### 已确认规则

- **P0-4-R1**：当前报告必须基于 effective evidence。
- **P0-4-R2**：invalidated evidence 保留用于审计、历史查看、debug，可展示但必须明确标记 invalidated，不进入当前报告。
- **P0-4-R3**：允许基于 invalidated evidence 生成 historical_report，但必须明确标注历史/已失效，不代表当前有效结论。

## 5.6 参数冲突

### FR-9：参数冲突必须显式处理

参数冲突包括同名冲突、alias 冲突、pending 参数与 known param 冲突、MCP suggested args 与用户输入冲突、LLM 抽取与高可信参数冲突。

### 已确认规则

- **P0-5-R1**：用户显式冲突值优先，但关键参数冲突必须从受影响 provenance step 触发 invalidation/rollback。
- **P0-5-R2**：LLM 抽取的冲突值不能覆盖高可信 known params，除非检测到明确用户修改意图；否则询问澄清。
- **P0-5-R3**：用户显式输入优先于 MCP suggested args，但必须通过 schema/candidate 校验。
- **P0-5-R4**：冲突参数若只影响当前尚未执行的 pending step，可直接覆盖 pending args，不触发回退。

## 5.7 CandidateSet 生命周期

### FR-10：系统必须管理候选集

MCP 返回 playbook、iteration、rank、operator、template、branch 等候选时，系统应创建 `CandidateSet`，用于多轮选择和序号解析。

### 已确认规则

- **P1-1-R1**：“第二个”等序号选择默认绑定最近 active CandidateSet。
- **P1-1-R2**：每个 `DiagnosisContext` 最多一个 primary active CandidateSet。
- **P1-1-R3**：CandidateSet 来源步骤失效时，该 CandidateSet 必须 invalidated。
- **P1-1-R4**：CandidateSet 使用全局稳定编号；分页展示仍保持全局编号。

## 5.8 自动执行治理

### FR-11：系统必须限制自动执行步数

自动补全增强后，系统不得无限自动执行 MCP step。

### 已确认规则

- **P1-2-R1**：默认 `max_auto_steps_per_turn = 5`。
- **P1-2-R2**：达到 5 步后暂停，展示已执行步骤摘要和下一步信息，询问用户是否继续。
- **P1-2-R3**：用户确认继续后，per-turn auto_count 重置；diagnosis-level total_auto_steps 保持累计。
- **P1-2-R4**：默认 `max_auto_steps_per_diagnosis = 20`。
- **P1-2-D1**：当前阶段暂不做 MCP tool risk classification。

## 5.9 Schema drift 与版本兼容

### 已确认规则

- **P1-3-R1**：resume 时发现 schema drift，优先使用最新 schema 自动迁移；缺参数再问用户。
- **P1-3-R2**：pending tool 或 selected playbook 不存在时，用原始目标和 known params 重新 search playbook，尝试迁移。
- **P1-3-R3**：旧参数中不再属于新 schema 的字段不传给 MCP，但保留审计。

## 5.10 Playbook 切换

### 已确认规则

- **P1-4-R1**：playbook switch 创建新的 effective diagnosis path；旧 path superseded，旧 evidence 不进入当前报告。
- **P1-4-R2**：切换 playbook 时不自动迁移任何参数；新 playbook 参数重新抽取或询问。
- **P1-4-R3**：模糊 playbook switch 意图必须澄清，不自动切换。

## 5.11 Compact context / token 治理

### 已确认规则

- **P1-5-R1**：`compact_for_llm` 默认排除 invalidated history 详细内容，只包含必要失效摘要。
- **P1-5-R2**：默认包含最近 3 个有效 completed steps 摘要。
- **P1-5-R3**：active CandidateSet 默认最多包含 20 个候选摘要；可先 deterministic filter。

## 5.12 前端体验

### 已确认规则

- **P1-6-R1**：前端需要 Diagnosis Context / Progress Panel。
- **P1-6-R2**：前端展示简化参数 provenance，详细 provenance 可展开。
- **P1-6-R3**：步骤面板支持历史步骤重新执行/重新选择；执行前展示下游失效影响并确认。
- **P1-6-R4**：前端展示简化 operation queue 状态，可展开查看详情。
- **P1-6-R5**：前端展示 paused diagnosis 列表，每个支持继续、取消、查看。

## 5.13 可观测性、审计与指标

### 已确认规则

- **P1-7-R1**：记录所有关键状态变化，形成 `DiagnosisAuditEvent`。
- **P1-7-R2**：`DiagnosisAuditEvent` 必须持久化到 session store / DB。
- **P1-7-R3**：提供 Prometheus/metrics 指标，用于观测交互效率、上下文一致性、队列、CandidateSet、schema drift、自动执行和报告。
- **P1-7-R4**：最终支持完整诊断 replay；MVP 可先做简化 timeline。

## 6. 验收标准

### 6.1 参数复用

- Given 用户初始输入包含 path；When 后续 schema 需要 path；Then 系统自动补全且不重复询问。
- Given MCP 前序输出包含 iteration/rank；When 后续 schema 需要这些参数；Then 系统自动复用并记录 provenance。

### 6.2 回退与失效

- Given 已执行 Step 1-5；When 用户修改 Step 2 参数；Then Step 2-5 旧结果 invalidated，旧 evidence 不进入当前报告。

### 6.3 Pending / Paused

- Given pending 等待参数；When 用户说“暂停”；Then diagnosis 进入 paused，pending 保留。
- Given 多个 paused diagnosis；When 用户裸“继续”；Then 恢复最近创建的 paused diagnosis。

### 6.4 并发与幂等

- Given 一个 MCP step 正在执行；When 另一个 mutation 到达；Then 入队，按 FIFO 处理。
- Given 同一 idempotency_key 重复提交；Then 只创建/处理一个 operation。

### 6.5 Schema drift

- Given pending schema 与最新 schema 不兼容；When resume；Then 使用新 schema 重新解析，缺参数再问。

### 6.6 报告

- Given 存在 invalidated evidence；When 生成 current_report；Then invalidated evidence 不被引用。

## 7. 分阶段交付

### Phase 1：上下文与参数复用

- `DiagnosisContext`；
- `ParameterResolver`；
- pending metadata 保存 context；
- compact context；
- effective known params；
- 基础 provenance。

### Phase 2：回退、失效与报告 effective evidence

- `InvalidationEngine`；
- rollback intent；
- invalidated evidence；
- `ReportEvidenceValidator`；
- historical_report 标记。

### Phase 3：并发队列、paused 多诊断、CandidateSet

- `OperationQueue`；
- idempotency；
- multiple paused contexts；
- `CandidateSet` 生命周期。

### Phase 4：reconciliation、schema drift、playbook switch

- `ReconciliationEngine`；
- schema drift migration；
- playbook migration/switch。

### Phase 5：前端与可观测性

- Diagnosis Panel；
- operation queue UI；
- paused diagnosis list；
- audit events；
- metrics；
- simplified timeline。

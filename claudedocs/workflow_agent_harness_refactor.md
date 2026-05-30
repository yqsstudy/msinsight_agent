# MSInsight Agent Harness 改造实施工作流

## 1. 工作流目标

基于：

- `docs/requirements.md`
- `docs/design.md`

将当前 `msinsight_agent` 从“内置 MCP 流程 DAG 编排型 Agent”改造为“上层 Agent Harness / Task Orchestrator”。目标是通过配置连接外部 MS-RAG 与 MSInsight MCP，完成普通聊天、知识问答、MCP 优先 profiling 诊断、RAG 后置增强、Evidence 存储、ExecutionPlan 展示、会话恢复和 Markdown 报告生成。

本计划只描述实施步骤，不直接执行代码修改。

## 2. 总体实施原则

1. **先计划与审计，再改主链路**：先补齐 ExecutionPlan、Evidence、Session 存储，再调整 Orchestrator。
2. **MCP 优先诊断**：分析类请求必须先走 MCP `search_profiler_tools` / `execute_profiler_tool`，RAG 只在条件满足时后置增强。
3. **普通聊天固定模板**：普通聊天只返回产品能力说明，不调用 LLM、RAG、MCP，不生成报告。
4. **知识问答只走 RAG**：知识类请求调用 MS-RAG，不调用 MCP；默认不生成持久化报告。
5. **不重复 MCP playbook**：Agent Harness 不维护 MCP 内部步骤 DAG，不绕过 MCP 调用 C++ 后端。
6. **显式 ExecutionPlan**：每轮请求生成可持久化、可展示、可恢复的 plan 和 steps。
7. **Evidence 优先**：所有用户输入、RAG 片段、MCP observation、系统降级和 Agent 结论都要能落库审计。
8. **渐进兼容**：保留现有 FastAPI、SSE、MCP transports、SessionStore、ReportGenerator 基础能力，避免一次性大拆。
9. **先后端闭环，再前端增强**：先让 API/SSE 主链路稳定，再做完整 UI 展示。
10. **外部服务手动启动**：第一阶段 RAG 与 MCP 均手动启动；Agent 只连接并做后台预检。

## 3. 阶段总览

| Phase | 名称 | 目标 | 依赖 |
| --- | --- | --- | --- |
| P0 | 基线清理与范围冻结 | 确认当前变更、清理非源码产物、冻结主入口 | 无 |
| P1 | 需求与文档收敛 | 将开放问题落为已确认决策，保持 requirements/design/workflow 一致 | P0 |
| P2 | 核心模型与配置 | 增加 chat intent、ExecutionPlan、ExecutionStep、配置项 | P1 |
| P3 | SQLite 持久化扩展 | plans、steps、evidence、pending_inputs、reports、feedback 可恢复 | P2 |
| P4 | Adapter 与健康检查 | RAG Client、MCP Gateway、MCP response parser、MCP 后台预检 | P2 |
| P5 | IntentRouter 与 ExecutionPlanner | 规则优先 + LLM fallback，按 intent 生成 plan | P2 + P3 |
| P6 | Orchestrator 主链路 | 普通聊天、知识问答、MCP 优先诊断、RAG 后置增强 | P3 + P4 + P5 |
| P7 | Streaming API 与 SSE 标准化 | 接入新 Orchestrator，输出 plan/step/evidence 事件 | P6 |
| P8 | 报告与反馈闭环 | Evidence 驱动 Markdown 报告，保存反馈 | P3 + P6 |
| P9 | 前端完整过程展示 | ExecutionPlan、step、evidence、pending input、report UI | P7 + P8 |
| P10 | 错误降级与系统状态 | MCP/RAG 降级、/api/system/status、可观测性 | P4 + P6 |
| P11 | 测试与验收 | 单测、集成、前端构建、验收场景 | P6-P10 |
| P12 | 文档与发布收口 | README/startup/API 调试说明 | P11 |

## 4. 依赖关系图

```text
P0 基线清理
  ↓
P1 文档收敛
  ↓
P2 核心模型与配置
  ├──────────────┬──────────────┐
  ↓              ↓              ↓
P3 持久化       P4 Adapter      P5 Router/Planner
  └──────┬───────┴──────┬───────┘
         ↓              ↓
      P6 Orchestrator 主链路
         ↓
      P7 Streaming API
         ├──────────────┐
         ↓              ↓
      P8 报告反馈      P9 前端展示
         └──────┬───────┘
                ↓
      P10 错误降级与系统状态
                ↓
      P11 测试与验收
                ↓
      P12 文档收口
```

## 5. Phase P0：基线清理与范围冻结

### 5.1 目标

确保后续实现基于可控工作区，避免把运行产物、数据库调试文件或旧流程误纳入功能实现。

### 5.2 任务

#### P0.1 工作区审计

检查：

- `git status --short`
- 已修改后端文件
- 已修改前端文件
- `agent-service/sessions/sessions.db`
- `__pycache__` 文件

产出：

- 确认哪些是功能代码；
- 哪些是运行产物；
- 哪些文档已完成；
- 哪些需要暂缓或排除提交。

验收：

- 明确 `__pycache__` 不应进入提交；
- 明确 `sessions.db` 是否保留为调试数据或从提交中排除；
- 明确本轮实现从哪个文档版本开始。

#### P0.2 主入口确认

检查：

- `agent-service/src/main.py`
- `agent-service/src/api/routes/streaming.py`
- `agent-service/src/api/routes/sessions.py`
- `agent-service/src/api/routes/reports.py`

验收：

- `/api/stream/message` 和 `/api/stream/continue` 是新 Orchestrator 主入口；
- 旧 `messages.py` / `agent_controller` / DAG 入口不再驱动新诊断主链路；
- 会话 API 能返回历史消息。

#### P0.3 旧 DAG 边界确认

检查：

- `agent-service/src/core/dag/*`
- `agent-service/src/core/tool_orchestrator.py`
- `agent-service/config/flows.yaml`

验收：

- `core/dag` 可保留，但不负责 MCP playbook 主流程；
- `flows.yaml` 不再定义 profiling 诊断步骤链；
- 不删除旧模块，除非后续明确清理。

## 6. Phase P1：需求与文档收敛

### 6.1 目标

把用户已确认的 10 个开放问题从“开放问题”变成明确需求，避免实现时反复摇摆。

### 6.2 任务

#### P1.1 更新 requirements 决策

目标文件：

- `docs/requirements.md`

需要落入已确认决策：

1. 普通聊天：固定产品说明，不接 LLM 自由聊天。
2. 意图识别：规则优先 + LLM 结构化分类兜底 + 低置信度澄清；阈值 0.85 / 0.60。
3. ExecutionPlan：完整记录 step 状态、输入、输出、耗时和失败原因。
4. 分析类 RAG：MCP 后置条件触发。
5. MCP 不可用：询问用户是否降级为 RAG 知识建议。
6. 知识问答：默认不生成持久化报告，用户要求时可生成。
7. 报告：条件触发。
8. 路径安全：只做格式校验。
9. MCP tools：启动后后台预检，请求时按需连接/复用。
10. 前端：展示完整 ExecutionPlan、step 状态、evidence、降级原因。

验收：

- `docs/requirements.md` 中不再把上述 10 项列为未决问题；
- `docs/design.md` 与 requirements 一致。

#### P1.2 更新 workflow 与设计一致性

目标文件：

- `claudedocs/workflow_agent_harness_refactor.md`

验收：

- workflow 中诊断路径为 MCP 优先；
- workflow 包含 ExecutionPlan；
- workflow 明确不执行实现。

## 7. Phase P2：核心模型与配置

### 7.1 目标

建立后续模块共享的稳定契约。

### 7.2 任务

#### P2.1 扩展 IntentType 与 OrchestratorState

目标文件：

- `agent-service/src/models/orchestration.py`

新增或调整：

- `IntentType.CHAT = "chat"`
- `IntentType.CONTINUE_ANALYSIS`
- `IntentType.REPORT_GENERATION`
- plan/step 相关 status 枚举或 Literal

验收：

- 普通聊天可以明确路由为 `chat`；
- 不再把普通聊天落入 `clarification`；
- 现有代码引用不破坏。

#### P2.2 新增 ExecutionPlan / ExecutionStep 模型

目标文件：

- `agent-service/src/models/orchestration.py`

模型：

- `ExecutionPlan`
- `ExecutionStep`
- `ExecutionPlanStatus`
- `ExecutionStepStatus`

验收：

- 字段包含 `id/session_id/user_message_id/intent/status/goal/steps/current_step_id/evidence_ids/metadata`；
- step 字段包含 `type/name/status/input/output/evidence_ids/error/timing/metadata`；
- 可通过 Pydantic 序列化为 SSE 和 SQLite JSON。

#### P2.3 扩展 PendingInput / Evidence 关联字段

目标文件：

- `agent-service/src/models/orchestration.py`
- `agent-service/src/models/evidence.py`

新增字段：

- `plan_id: Optional[str]`
- `step_id: Optional[str]`

验收：

- 老数据缺少 plan_id/step_id 时仍可加载；
- 新 evidence 可关联到具体 plan step。

#### P2.4 扩展配置模型

目标文件：

- `agent-service/src/models/config.py`
- `agent-service/src/storage/config_store.py`
- `agent-service/config/config.yaml`

配置项：

```yaml
orchestrator:
  chat_mode: "fixed_template"
  intent_strategy: "rule_first_llm_fallback"
  high_confidence_threshold: 0.85
  low_confidence_threshold: 0.60
  auto_execute: true
  max_auto_steps: 5
  validate_path_mode: "format_only"
  rag_after_mcp_policy: "conditional"
  mcp_unavailable_policy: "ask_before_rag_fallback"
  report_policy: "conditional"

mcp:
  health_check_on_startup: true
  health_check_mode: "background"
  required_meta_tools:
    - "search_profiler_tools"
    - "execute_profiler_tool"
```

验收：

- 缺省配置可启动；
- 旧 config.yaml 不完整时有合理默认值；
- API key 不进入日志。

## 8. Phase P3：SQLite 持久化扩展

### 8.1 目标

让会话、消息、计划、步骤、证据、待输入、报告和反馈都可恢复。

### 8.2 任务

#### P3.1 增加 execution_plans 表

目标文件：

- `agent-service/src/storage/session_store.py`

新增表：

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
```

验收：

- 启动幂等创建；
- 可按 session 查询 plan；
- 不破坏已有 sessions/messages。

#### P3.2 增加 execution_steps 表

新增表：

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
```

验收：

- step 状态可独立更新；
- step 可记录 input/output/error/elapsed_ms。

#### P3.3 扩展 evidence / pending_inputs / reports

目标：

- 增加 `plan_id`、`step_id` 字段；
- 保持旧表兼容。

策略：

- SQLite 启动时检查列是否存在；
- 缺列时 `ALTER TABLE ADD COLUMN`；
- 不做破坏性迁移。

验收：

- 老数据库可启动；
- 新 evidence/pending/report 可关联 plan/step。

#### P3.4 增加 Store 方法

目标文件：

- `agent-service/src/storage/session_store.py`

新增方法：

```python
create_execution_plan(plan)
update_execution_plan(plan)
get_execution_plan(plan_id)
list_execution_plans(session_id)
create_execution_step(step)
update_execution_step(step)
list_execution_steps(plan_id)
append_step_evidence(step_id, evidence_id)
append_plan_evidence(plan_id, evidence_id)
```

验收：

- Orchestrator 可在执行中更新 plan/step；
- Session API 可返回 plans 和 steps。

## 9. Phase P4：Adapter 与健康检查

### 9.1 目标

让 Orchestrator 只依赖稳定内部 Adapter，不依赖外部服务细节。

### 9.2 任务

#### P4.1 RAG Client 校准

目标文件：

- `agent-service/src/adapters/rag_client.py`

要求：

- `retrieve()` 调 `/api/v1/retrieve`；
- `qa()` 调 `/api/v1/qa`；
- `health()` 调健康接口或返回 unavailable；
- 保存 raw item；
- 正确映射 `doc_id/chunk_id/title/section_title/path/url/final_score`。

验收：

- RAG 返回信息不丢失；
- RAG 不可用抛出统一 `RAG_UNAVAILABLE`；
- 纯知识问答不调用 MCP。

#### P4.2 MCP Gateway 校准

目标文件：

- `agent-service/src/adapters/mcp_gateway.py`
- `agent-service/src/adapters/mcp_response_parser.py`

要求：

- 只调用 `search_profiler_tools` 和 `execute_profiler_tool`；
- 不直接调用 MCP 内部工具；
- 解析 playbook candidates、auto selected playbook、next step、schema、progress、requires user input。

验收：

- search 结果保存为 MCP observation；
- execute 结果保存 raw；
- 解析失败时停止自动推进并总结，不丢 evidence。

#### P4.3 MCP 后台预检

建议新增：

- `agent-service/src/core/health_probe.py`
- 或扩展现有 `observability/health.py`

行为：

- Agent 启动后后台验证 MCP 配置；
- stdio 模式可短暂 initialize/list_tools 后关闭；
- SSE/WebSocket/HTTP 模式 ping/list_tools；
- 校验 required meta tools 是否存在；
- 结果进入 system status。

验收：

- 预检失败不阻塞后端启动；
- `/api/system/status` 可展示 MCP unavailable 和 last_error；
- 普通聊天和 RAG 问答不受 MCP 预检失败影响。

## 10. Phase P5：IntentRouter 与 ExecutionPlanner

### 10.1 目标

把用户消息稳定转换为 IntentDecision 和 ExecutionPlan。

### 10.2 任务

#### P5.1 IntentRouter 规则优先

目标文件：

- `agent-service/src/core/intent_router.py`

规则优先级：

1. active pending input → `continue_analysis`
2. 报告/总结成报告/整理成方案 → `report_generation`
3. profiling 路径 + 分析/诊断/快慢卡/通信慢 → `profiling_analysis`
4. 分析/诊断/定位/瓶颈/快慢卡/通信慢/算子慢 → `diagnosis`
5. 找资料/检索/相关文档/依据 → `knowledge_retrieve`
6. 怎么/如何/是什么/参数/用法/msprof/MindStudio → `knowledge_qa`
7. 问候/你能做什么 → `chat`
8. 其他 → `clarification`

验收：

- “分析 D:\data\...\e2e 是否存在快慢卡问题” → `profiling_analysis`；
- “msprof 怎么分析通信耗时” → `knowledge_qa`；
- “你好/你能做什么” → `chat`；
- `chat` 不触发 RAG/MCP。

#### P5.2 LLM fallback 分类

目标：

- 中置信度时调用 LLM 结构化分类；
- 低置信度时澄清。

验收：

- LLM 输出必须 schema 校验；
- LLM 只分类，不执行工具；
- `confidence < 0.60` 不调用 RAG/MCP。

#### P5.3 ExecutionPlanner

建议文件：

- `agent-service/src/core/execution_planner.py`

按 intent 生成：

- Chat Plan：`chat_response`
- Knowledge Plan：`rag_qa/rag_retrieve` + `evidence_fusion`
- Profiling Plan：`mcp_search` + `user_input?` + `mcp_execute*` + `rag_retrieve?` + `evidence_fusion` + `report_generation?`
- Report Plan：`load_session_evidence` + `rag_retrieve?` + `report_generation`

验收：

- 每轮请求持久化 plan；
- SSE 可发出 `execution_plan_created`；
- plan 中分析类 step 顺序体现 MCP 优先。

## 11. Phase P6：Orchestrator 主链路

### 11.1 目标

实现四条可运行路径：chat、knowledge、diagnosis/profiling、report。

### 11.2 任务

#### P6.1 Chat 路径

流程：

```text
message → intent=chat → plan=chat_response → fixed template → completed
```

验收：

- 不调用 RAG；
- 不调用 MCP；
- 不生成 report；
- 保存 user message 和 assistant message。

#### P6.2 Knowledge 路径

流程：

```text
message → intent=knowledge_qa/retrieve → RAG qa/retrieve → save rag_evidence → answer → completed
```

验收：

- 不调用 MCP；
- RAG evidence 保存 raw；
- 默认不保存 report；
- 用户要求报告时走 report plan。

#### P6.3 Profiling / Diagnosis 路径

正确流程：

```text
message
→ intent=profiling_analysis/diagnosis
→ create plan
→ MCP search_profiler_tools
→ save mcp_observation
→ 如果需要 playbook 选择：user_input_required
→ 如果缺 profiling 路径：user_input_required
→ MCP execute_profiler_tool
→ 根据 MCP next_step 自动推进最多 max_auto_steps
→ 按条件 RAG retrieve 后置增强
→ evidence_fusion
→ analysis_result
→ 条件触发 report_generation
```

验收：

- 分析类请求不再先调用 RAG；
- MCP unavailable 时询问是否降级 RAG；
- RAG unavailable 时 MCP 可继续；
- 每个 MCP 结果保存 evidence；
- `user_input_required` 可恢复执行。

#### P6.4 Continue 路径

流程：

```text
/api/stream/continue
→ load active pending_input
→ save user_input evidence
→ resolve pending_input
→ 根据 resume_action 回到对应 plan step
```

resume_action：

- `provide_path`
- `select_playbook`
- `provide_params`
- `confirm_execute`
- `fallback_to_rag`

验收：

- 用户补路径后继续 MCP execute；
- 用户选择 playbook 后继续 search/execute；
- 用户同意 RAG 降级后调用 RAG 并说明非实测。

#### P6.5 RAG 后置条件判断

建议函数：

```python
should_call_rag_after_mcp(plan, mcp_results, user_message) -> bool
```

触发条件：

- MCP 完成且需要解释指标；
- MCP 发现明确问题；
- MCP 置信度不足或结论不完整；
- 用户要求解释/依据/建议；
- 用户要求报告；
- MCP 不可用且用户同意降级。

验收：

- 后置 RAG 不影响 MCP 优先顺序；
- RAG query 由用户目标 + MCP observation 摘要构造。

## 12. Phase P7：Streaming API 与 SSE 标准化

### 12.1 目标

让前端完整感知 plan、step、evidence、错误和报告。

### 12.2 任务

#### P7.1 `/api/stream/message`

目标文件：

- `agent-service/src/api/routes/streaming.py`

验收：

- 调用 `Orchestrator.handle_message()`；
- 输出 `text/event-stream`；
- event envelope 带 `event_id/session_id/timestamp/data`。

#### P7.2 `/api/stream/continue`

验收：

- 校验 active pending input；
- 调用 `Orchestrator.continue_with_input()`；
- 继续输出 SSE。

#### P7.3 新增 plan/step 事件

事件：

- `execution_plan_created`
- `execution_step_started`
- `execution_step_completed`
- `execution_step_failed`

验收：

- 前端可通过事件构建 Timeline；
- 错误事件包含 recoverable、degradation_options、evidence_id。

## 13. Phase P8：报告与反馈闭环

### 13.1 目标

让报告成为 evidence 驱动的可审计产物，而不是普通回答摘要。

### 13.2 任务

#### P8.1 ReportGenerator 重构

目标文件：

- `agent-service/src/core/report_generator.py`

输入：

- session_id
- user_goal
- evidence list

输出：

- Markdown content
- evidence_ids
- metadata

验收：

- 包含问题摘要、当前结论、证据链、MCP 实测结果、RAG 知识依据、根因排序、建议、不确定性、引用来源；
- 区分 confirmed facts / inference / knowledge basis / uncertainty；
- 不声称未执行的 MCP 分析。

#### P8.2 报告触发策略

触发：

- 用户明确要求；
- MCP 完成关键阶段且发现明确问题；
- 用户要求复盘/分享；
- 系统策略配置自动阶段报告。

验收：

- 纯知识问答默认不生成 report；
- 用户要求“整理成报告/方案/文档”时可以生成并保存。

#### P8.3 Feedback 保存

目标：

- 记录采纳情况和评论；
- 不自动写回 RAG corpus。

验收：

- `POST /api/feedback` 可写入；
- report view 可提交反馈。

## 14. Phase P9：前端完整过程展示

### 14.1 目标

React 前端作为统一入口，展示完整 ExecutionPlan、step 状态、RAG/MCP evidence、降级原因和报告入口。

### 14.2 任务

#### P9.1 TypeScript 类型扩展

目标文件：

- `agent-web/src/types/index.ts`

新增类型：

- `ExecutionPlan`
- `ExecutionStep`
- `Evidence`
- `PendingInput`
- `TraceEvent`
- `Report`

验收：

- SSE 事件 data 有类型承载；
- session detail 可包含 messages/plans/evidence/reports。

#### P9.2 Store 扩展

目标文件：

- `agent-web/src/stores/index.ts`

新增状态：

- `plans`
- `activePlanId`
- `evidence`
- `reports`
- `traceEvents`
- `pendingInput`

验收：

- 历史会话恢复后，消息、计划、证据、报告可见。

#### P9.3 ChatView SSE 处理

目标文件：

- `agent-web/src/components/ChatView.tsx`

处理事件：

- `execution_plan_created`
- `execution_step_started`
- `execution_step_completed`
- `execution_step_failed`
- `intent_detected`
- `rag_retrieval`
- `mcp_tool_start`
- `mcp_tool_result`
- `user_input_required`
- `analysis_result`
- `report_ready`
- `error`

验收：

- 错误有可见提示；
- pending input 渲染为输入/选择/确认；
- report_ready 展示报告入口。

#### P9.4 新增展示组件

建议组件：

- `TraceTimeline.tsx`
- `EvidencePanel.tsx`
- `PendingInputPanel.tsx`
- `ReportView.tsx`

验收：

- Timeline 展示完整计划；
- Evidence 可展开 raw metadata；
- Report Markdown 可展示；
- 降级原因可见。

## 15. Phase P10：错误降级与系统状态

### 15.1 目标

保证外部服务不可用时会话不丢失，用户知道当前结果边界。

### 15.2 任务

#### P10.1 错误分类统一

错误码：

- `INTENT_UNCLEAR`
- `RAG_UNAVAILABLE`
- `MCP_UNAVAILABLE`
- `MCP_TOOL_FAILED`
- `MCP_PARAM_MISSING`
- `MCP_PLAYBOOK_CHOICE_REQUIRED`
- `PATH_INVALID_FORMAT`
- `REPORT_GENERATION_FAILED`
- `STORAGE_ERROR`

验收：

- SSE error 与 HTTP error 使用一致结构；
- 前端能显示 `message/code/recoverable/degradation_options`。

#### P10.2 降级策略

验收场景：

- RAG 不可用 + 分析请求：继续 MCP，报告说明缺少知识依据；
- RAG 不可用 + 知识问答：提示 RAG 不可用；
- MCP 不可用 + 分析请求：询问是否降级 RAG；
- 用户同意降级：调用 RAG，并说明非实测；
- SQLite 写入失败：不声称保存成功。

#### P10.3 `/api/system/status`

聚合状态：

- Agent
- RAG
- MCP
- Storage
- last_error
- last_checked_at

验收：

- MCP 预检失败可见；
- 普通聊天/RAG 问答不被 MCP unavailable 标成全系统不可用。

## 16. Phase P11：测试与验收

### 16.1 后端单元测试

| 模块 | 覆盖 |
| --- | --- |
| IntentRouter | chat、knowledge、diagnosis、profiling、report、clarification |
| ExecutionPlanner | 不同 intent 生成正确 step 顺序 |
| SessionStore | plans、steps、evidence、pending、reports CRUD |
| RAGClient | 字段映射、raw 保存、不可用错误 |
| MCPGateway | search、execute、parser、不可用错误 |
| InteractionPolicy | 自动推进、用户输入、副作用、max_auto_steps |
| ReportGenerator | Markdown 结构、evidence 引用、分类表达 |

### 16.2 后端集成测试

| 场景 | 验收 |
| --- | --- |
| 普通聊天 | 不调用 RAG/MCP，返回固定说明 |
| 知识问答 | 调用 RAG，不调用 MCP，不生成 report |
| profiling 分析 | MCP search 先于 RAG，保存 MCP evidence |
| 缺路径 | `user_input_required`，补充后恢复 |
| 多 playbook | 展示候选，用户选择后继续 |
| MCP 不可用 | 询问 RAG 降级 |
| RAG 不可用 | MCP 分析继续 |
| 报告生成 | 保存 Markdown，引用 evidence |

### 16.3 前端验证

- `npm run build` 通过；
- SSE 所有事件可渲染；
- 历史会话恢复 messages/plans/evidence/reports；
- PendingInputPanel 可提交 continue；
- SystemStatus 不因 MCP unavailable 导致全挂。

### 16.4 UI 手工验收

必须手工验证：

1. 问“你好/你能做什么”；
2. 问“msprof 怎么分析通信耗时”；
3. 问“分析 D:/data/.../e2e 是否存在快慢卡问题”；
4. 模拟 MCP 不可用；
5. 模拟 RAG 不可用；
6. 从历史会话恢复并查看 evidence/report。

## 17. Phase P12：文档与发布收口

### 17.1 文档更新

目标文件：

- `README.md`
- `agent-service/README.md`
- `agent-web/README.md`
- `docs/startup.md`
- `docs/requirements.md`
- `docs/design.md`

内容：

- RAG 手动启动方式；
- MCP stdio/SSE/WebSocket 配置；
- Agent Harness 启动方式；
- SSE 事件说明；
- Evidence / Report 查看方式；
- MCP unavailable / RAG unavailable 调试说明。

### 17.2 旧流程边界说明

明确：

- `core/dag` 保留但不再驱动 MCP playbook；
- `flows.yaml` 不再定义 profiling 诊断链路；
- 新主链路入口是 Orchestrator。

## 18. 推荐提交切分

1. `docs: align agent harness requirements and workflow`
2. `feat: add execution plan models and config`
3. `feat: persist execution plans and steps`
4. `feat: associate evidence reports and pending inputs with plans`
5. `feat: add mcp health preflight and status aggregation`
6. `feat: add execution planner`
7. `feat: update intent routing for chat and profiling analysis`
8. `feat: make diagnosis flow mcp-first`
9. `feat: add conditional rag enhancement after mcp`
10. `feat: standardize orchestration sse events`
11. `feat: expose plans evidence and reports in session api`
12. `feat: render execution timeline evidence and reports`
13. `test: cover orchestrator planner adapters and storage`
14. `docs: update startup and debugging guide`

## 19. 实施检查清单

### 文档

- [ ] requirements 开放问题已收敛
- [ ] design 与 requirements 一致
- [ ] workflow 与 design 一致

### 后端模型与存储

- [ ] `IntentType.CHAT` 已增加
- [ ] `ExecutionPlan` / `ExecutionStep` 模型完成
- [ ] plan/step SQLite 表完成
- [ ] evidence/pending/reports 支持 plan_id/step_id
- [ ] Session API 返回 plans/evidence/reports

### Adapter 与健康检查

- [ ] RAG Client 字段映射和 raw 保存完成
- [ ] MCP Gateway 只调用 meta tools
- [ ] MCP response parser 完成
- [ ] MCP 后台预检完成
- [ ] `/api/system/status` 完成

### Orchestrator

- [ ] Chat 固定模板路径完成
- [ ] Knowledge RAG-only 路径完成
- [ ] Profiling MCP-first 路径完成
- [ ] RAG 后置条件完成
- [ ] Continue 恢复完成
- [ ] MCP 不可用询问 RAG 降级完成
- [ ] RAG 不可用时 MCP 继续完成

### SSE / API

- [ ] `execution_plan_created` 完成
- [ ] `execution_step_started/completed/failed` 完成
- [ ] error event 标准化完成
- [ ] `/api/stream/message` 接入新 Orchestrator
- [ ] `/api/stream/continue` 接入新 Orchestrator

### 前端

- [ ] TS 类型扩展完成
- [ ] Store 支持 plans/evidence/reports
- [ ] ChatView 处理新 SSE 事件
- [ ] TraceTimeline 完成
- [ ] EvidencePanel 完成
- [ ] PendingInputPanel 完成
- [ ] ReportView 完成
- [ ] 历史会话恢复完整上下文

### 测试

- [ ] IntentRouter 单测
- [ ] ExecutionPlanner 单测
- [ ] SessionStore 单测
- [ ] RAGClient 单测
- [ ] MCPGateway 单测
- [ ] InteractionPolicy 单测
- [ ] Orchestrator 集成测试
- [ ] Streaming API 测试
- [ ] Frontend build 通过
- [ ] UI 手工验收完成

## 20. 关键风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| MCP 返回主要是文本，next_step 解析脆弱 | 自动推进不稳定 | Parser 独立封装；解析失败则停止自动推进并提示用户；推动 MCP 结构化返回 |
| 旧 DAG 与新 Orchestrator 并存 | 调用链混乱 | streaming 主入口只走新 Orchestrator；旧 DAG 保留但不接主链路 |
| SQLite 旧库结构不一致 | 启动失败或历史数据丢失 | 使用 `CREATE TABLE IF NOT EXISTS` 和安全 `ALTER TABLE ADD COLUMN` |
| 诊断流程误回到 RAG-first | 产品路径偏离 | 测试中断言 profiling 请求 MCP search 先于 RAG |
| MCP stdio 启动失败 | 分析不可用 | 后台预检 + system status + 用户同意后 RAG 降级 |
| 自动执行过度 | 用户失控 | `max_auto_steps=5`、副作用确认、候选项确认 |
| LLM 分类或报告幻觉 | 结论不可信 | LLM 只做结构化分类；报告必须引用 evidence，区分事实/推断/不确定 |
| 前端事件过多 | UI 混乱 | TraceTimeline 汇总 step，EvidencePanel 承载详情 |

## 21. 第一版完成定义

第一版完成需满足：

1. 用户可以创建和恢复会话。
2. 普通聊天返回固定产品说明，不调用 RAG/MCP。
3. 知识问题调用 MS-RAG，返回来源，不调用 MCP。
4. profiling 分析问题先调用 MCP `search_profiler_tools`。
5. profiling 路径充分时调用 MCP `execute_profiler_tool`。
6. MCP observation、RAG evidence、user input、system event 均保存到 `sessions.db`。
7. 每轮请求生成 ExecutionPlan，前端可展示 step 状态。
8. MCP 需要选择或参数时发出 `user_input_required`，用户补充后可恢复。
9. MCP 完成后按条件调用 RAG 后置增强。
10. 用户要求或策略触发时生成 Markdown 报告并保存。
11. RAG 不可用时分析可继续 MCP，并说明缺少知识依据。
12. MCP 不可用时询问是否降级 RAG，并说明无法基于真实 profiling 验证。
13. 前端能展示诊断进度、证据、降级原因和报告。
14. 后端单测、集成测试和前端 build 通过。

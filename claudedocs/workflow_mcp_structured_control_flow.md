# MCP 结构化流程控制实施工作流

## 1. 工作流目标

基于以下文档生成实施计划：

- `docs/mcp_structured_control_flow_requirements.md`
- `docs/mcp_structured_control_flow_design.md`

目标是在 demo 阶段完成 MCP 结构化流程控制闭环：

1. `ms_mcp` 所有 `execute_profiler_tool` 结构化结果包含 `control_flow + data`；
2. `agent-service` 严格解析 `raw.control_flow`，不再依赖 Markdown / text 控制流；
3. `agent-service` 支持 `SUCCESS`、`BLOCKED`、`RETRYABLE_ERROR`、`FATAL_ERROR`、`NEEDS_USER_INPUT` 的流程分派；
4. `agent-web` 根据结构化 `status` / `reason` 渲染等待、重试、输入、错误 UI；
5. 通过单元测试、集成测试与端到端 mock 流程验证核心行为。

本工作流只定义实施计划，不执行代码修改。

---

## 2. 总体实施策略

### 2.1 推荐顺序

采用后端契约优先、Agent 仲裁随后、前端渲染最后的顺序：

```text
Phase 0: 基线确认与测试夹具准备
   ↓
Phase 1: ms_mcp 结构化响应契约落地
   ↓
Phase 2: agent-service 数据模型与 MCP 解析落地
   ↓
Phase 3: agent-service Orchestrator / InteractionPolicy 控制流分派
   ↓
Phase 4: agent-web 结构化 UI 渲染
   ↓
Phase 5: 端到端验证与回归
```

### 2.2 并行策略

可并行的工作：

- Phase 1 的 MCP 包装模型与 Phase 2 的 Agent 数据模型可以并行；
- Phase 4 前端类型和静态 UI 组件可以在 Phase 2 SSE payload 形态确定后并行；
- 单元测试可随各模块同步编写。

不可提前并行的工作：

- 前端真实事件联调依赖 Agent SSE payload 定稿；
- Orchestrator 自动重试依赖 MCPGateway 已能稳定返回 `ControlFlow`；
- E2E 测试依赖 MCP 与 Agent 两端都完成核心契约。

---

## 3. 关键依赖图

```text
[需求/设计文档]
      │
      ├── [T1 MCP control_flow 模型/包装]
      │          │
      │          └── [T2 MCP execute_profiler_tool 统一出口]
      │                    │
      │                    └── [T3 MCP 契约测试]
      │
      ├── [T4 Agent ControlFlow 模型]
      │          │
      │          └── [T5 MCPResponseParser 结构化解析]
      │                    │
      │                    └── [T6 MCPGateway execute 结果归一化]
      │                              │
      │                              └── [T7 Orchestrator 控制流分派]
      │                                        │
      │                                        └── [T8 InteractionPolicy retry/wait 策略]
      │                                                  │
      │                                                  └── [T9 Agent 测试]
      │
      └── [T10 Frontend 类型]
                 │
                 └── [T11 Frontend 控制流组件]
                           │
                           └── [T12 ChatView SSE 事件接入]
                                     │
                                     └── [T13 Frontend 测试]

[T3] + [T9] + [T13] ──> [T14 E2E mock 流程验证]
```

---

## 4. Phase 0：基线确认与测试夹具准备

### 4.1 目标

在正式实现前确认当前主 demo playbook、MCP 执行出口、Agent orchestration 路径、前端 SSE 路径，准备后续验证用例。

### 4.2 任务

#### T0.1 确认主 demo playbook 与内部工具路径

范围：

- `mcp_service_code/ms_mcp/`
- playbook YAML 目录；
- 内部工具注册目录；
- `execute_profiler_tool` 实现路径。

输出：

- 记录主 demo playbook 的 initial step 与 next step；
- 标记哪些内部工具需要返回 `SUCCESS`、`BLOCKED`、`NEEDS_USER_INPUT`、`FATAL_ERROR`。

验收：

- 明确至少一个 demo playbook 可覆盖：
  - `SUCCESS`；
  - `BLOCKED / WAITING_FOR_EVENT`；
  - `NEEDS_USER_INPUT`；
  - `FATAL_ERROR`。

#### T0.2 准备 mock MCP 响应样例

准备 JSON fixture：

- `success_with_next_step.json`
- `blocked_waiting_event.json`
- `retryable_error_timeout.json`
- `fatal_error_invalid_parameter.json`
- `needs_user_input_missing_parameter.json`
- `invalid_missing_control_flow.json`
- `invalid_unknown_status.json`

验收：

- fixture 与需求文档枚举一致；
- 每个 fixture 都能用于 Agent parser 单元测试。

### 4.3 检查点

- 不改业务逻辑；
- 只确认路径与准备测试样例；
- 若发现设计中的文件路径与实际代码不一致，先更新设计/工作流备注，再实施。

---

## 5. Phase 1：ms_mcp 结构化响应契约落地

### 5.1 目标

让 MCP 服务端通过统一出口确保所有 `execute_profiler_tool` 结构化结果都包含 `control_flow + data`。

### 5.2 任务

#### T1.1 定义 MCP 端 control flow 常量与帮助函数

建议新增或放置在 MCP 公共模块：

- `ControlFlowStatus`
- `ControlFlowReason`
- `wrap_success()`
- `wrap_blocked()`
- `wrap_retryable_error()`
- `wrap_fatal_error()`
- `wrap_needs_user_input()`

依赖：无。

验收：

- status 枚举只包含：
  - `SUCCESS`
  - `BLOCKED`
  - `RETRYABLE_ERROR`
  - `FATAL_ERROR`
  - `NEEDS_USER_INPUT`
- reason 枚举与需求文档一致；
- wrapper 输出必须包含 `control_flow` 与 `data`。

#### T1.2 改造 `execute_profiler_tool` 统一出口

范围：

- MCP meta-tool `execute_profiler_tool` 实现；
- 内部工具结果归一化路径；
- navigator 生成 `next_step` / `progress` 的位置。

实施要求：

- 成功结果包装为 `SUCCESS`；
- `next_step` 使用结构化字段返回，不能只写入 Markdown；
- `progress` 使用结构化字段返回；
- Markdown 只保留人类可读内容。

依赖：T1.1。

验收：

- 任意成功内部工具执行结果都能得到：

```json
{
  "control_flow": { "status": "SUCCESS" },
  "data": {},
  "next_step": null
}
```

#### T1.3 映射阻塞场景

范围：

- 等待 `clusterCompleted`；
- 等待 profiling / timeline / cluster / memory 数据生成；
- 其他当前会输出 `BLOCKED:` 或等待文本的场景。

实施要求：

- 返回 `BLOCKED`；
- `reason = WAITING_FOR_EVENT` 时必须包含 `event_name`；
- 涉及异步任务时必须包含 `operation_id`；
- `retryable = true`；
- 提供 `suggested_retry_after_ms`。

依赖：T1.2。

验收：

```json
{
  "control_flow": {
    "status": "BLOCKED",
    "reason": "WAITING_FOR_EVENT",
    "event_name": "clusterCompleted",
    "operation_id": "...",
    "retryable": true,
    "suggested_retry_after_ms": 5000
  },
  "data": {}
}
```

#### T1.4 映射用户输入场景

范围：

- 缺少 profile path；
- 缺少 rank / device / operator / step 参数；
- 需要用户选择或确认的内部工具。

实施要求：

- 可由用户补充时返回 `NEEDS_USER_INPUT`；
- 必须包含 `required_inputs`；
- 不再只通过中文文本提示参数缺失。

依赖：T1.2。

验收：

```json
{
  "control_flow": {
    "status": "NEEDS_USER_INPUT",
    "reason": "MISSING_REQUIRED_PARAMETER",
    "retryable": false,
    "required_inputs": [
      { "name": "profile_path", "type": "string", "description": "请提供 profiling 数据路径" }
    ]
  },
  "data": {}
}
```

#### T1.5 映射错误场景

实施要求：

- 临时后端错误：`RETRYABLE_ERROR / BACKEND_ERROR`；
- 超时可重试：`RETRYABLE_ERROR / TIMEOUT`；
- 参数非法：`FATAL_ERROR / INVALID_PARAMETER`；
- playbook 配置错误：`FATAL_ERROR / BACKEND_ERROR`。

依赖：T1.2。

验收：

- 每类错误都有结构化 `status` / `reason`；
- 不依赖 `ERROR:` 文本作为机器协议。

#### T1.6 MCP 单元测试

建议测试：

- 成功响应包含 `SUCCESS`；
- 等待事件响应包含 `BLOCKED`、`event_name`、`operation_id`；
- 参数缺失响应包含 `NEEDS_USER_INPUT`、`required_inputs`；
- fatal error 包含 `retryable=false`；
- text 中不再出现用于机器解析的 `BLOCKED:`。

依赖：T1.1-T1.5。

验收命令：

```bash
cd mcp_service_code/ms_mcp
python -m pytest tests/ -v
```

---

## 6. Phase 2：agent-service 模型与 MCP 解析落地

### 6.1 目标

让 Agent 端能严格解析 MCP 结构化响应，归一化协议错误，并让 `MCPGateway.execute_profiler_tool()` 返回携带 `ControlFlow` 的 `MCPToolResult`。

### 6.2 任务

#### T2.1 新增 Agent 端 ControlFlow 模型

建议位置：

- `agent-service/src/models/control_flow.py`

或合入：

- `agent-service/src/models/orchestration.py`

模型：

- `ControlFlowStatus`
- `ControlFlowReason`
- `RequiredInput`
- `ControlFlow`
- `ControlFlowDecision`
- `ControlFlowRetryState`

依赖：T1.1 可并行，但枚举必须一致。

验收：

- Pydantic 模型可解析需求文档中的所有示例；
- 枚举不接受未知 status/reason。

#### T2.2 扩展 `MCPToolResult`

范围：

- `agent-service/src/models/orchestration.py`

新增字段：

- `control_flow: ControlFlow`
- `data: dict[str, Any]`

实施要求：

- `success` 由 `control_flow.status` 派生；
- `BLOCKED` 与 `NEEDS_USER_INPUT` 不视为 fatal failure；
- `RETRYABLE_ERROR` 与 `FATAL_ERROR` 视为 `success=false`。

依赖：T2.1。

验收：

- 现有构造 `MCPToolResult` 的代码全部更新；
- 类型检查/单元测试不因新增必填字段失败。

#### T2.3 改造 `MCPResponseParser`

范围：

- `agent-service/src/adapters/mcp_response_parser.py`

新增方法：

- `parse_control_flow(raw)`
- `validate_control_flow(control_flow)`
- `normalize_protocol_error(error)`
- `parse_next_step_from_raw(raw)`

移除或降级：

- 不再用 `requires_user_input(text)` 做流程判断；
- 不再用 text marker 判断 blocked/error；
- `parse_next_step()` 不再依赖执行结果 Markdown。

依赖：T2.1。

验收：

- 缺失 `control_flow` 归一化为 `FATAL_ERROR / MCP_PROTOCOL_ERROR`；
- 非法 status 归一化为协议错误；
- `NEEDS_USER_INPUT` 缺失 `required_inputs` 归一化为协议错误；
- `BLOCKED / WAITING_FOR_EVENT` 缺失 `event_name` 归一化为协议错误。

#### T2.4 改造 `MCPGateway.execute_profiler_tool()`

范围：

- `agent-service/src/adapters/mcp_gateway.py`

实施要求：

- 提取 raw；
- 调用 `parse_control_flow(raw)`；
- 从 `raw.data` 读取业务数据；
- 从 `raw.next_step` 读取下一步；
- 返回包含 `control_flow` 与 `data` 的 `MCPToolResult`；
- 不再使用 `text.startswith("ERROR")` 判断失败；
- 不再使用文本 marker 设置 `requires_user_input`。

依赖：T2.2、T2.3。

验收：

- mock raw 中 `next_step` 能正确变为 `MCPNextStep`；
- mock raw 缺失 `control_flow` 时不抛无结构异常，而是返回协议错误结果；
- `result.requires_user_input` 只由 `control_flow.status == NEEDS_USER_INPUT` 派生。

#### T2.5 Agent parser/gateway 单元测试

建议新增或扩展：

- `agent-service/tests/test_mcp_response_parser.py`
- `agent-service/tests/test_mcp_gateway_control_flow.py`

覆盖：

- success；
- blocked；
- retryable error；
- fatal error；
- needs user input；
- missing control_flow；
- unknown status；
- structured next_step。

依赖：T2.1-T2.4。

验收命令：

```bash
cd agent-service
pytest tests/test_mcp_response_parser.py tests/test_mcp_gateway_control_flow.py -v
```

---

## 7. Phase 3：agent-service Orchestrator 与策略落地

### 7.1 目标

让 Orchestrator 根据 `control_flow.status` 和 `reason` 执行继续、自动等待、自动重试、暂停用户输入、终止流程。

### 7.2 任务

#### T3.1 增加 control_flow 配置

范围：

- `agent-service/config/config.yaml`
- `agent-service/src/models/config.py`

新增配置：

```yaml
control_flow:
  enabled: true
  strict_protocol: true
  max_auto_retries: 3
  max_total_wait_ms: 30000
  default_retry_after_ms: 3000
  max_retry_after_ms: 10000
  emit_waiting_events: true
  pause_on_blocked_after_retries: true
```

依赖：T2.1。

验收：

- 配置可加载；
- 未配置时有合理默认值；
- demo 阶段 `enabled` 与 `strict_protocol` 默认为 true。

#### T3.2 扩展 `InteractionPolicy`

范围：

- `agent-service/src/core/interaction_policy.py`

新增：

- `decide_after_control_flow()`；
- retry delay clamp；
- retry count 与 total wait 检查；
- `BLOCKED` 超限暂停策略；
- `RETRYABLE_ERROR` 超限 recoverable error 策略。

依赖：T3.1。

验收：

- `BLOCKED + retryable=true` 阈值内返回 `auto_retry`；
- 超过 `max_auto_retries` 返回 `pause_waiting`；
- 超过 `max_total_wait_ms` 返回 `pause_waiting` 或 `fail`；
- `FATAL_ERROR` 返回 `fail`；
- `NEEDS_USER_INPUT` 返回 `require_user_input`。

#### T3.3 改造 `_execute_mcp_chain()` 控制流分派

范围：

- `agent-service/src/core/orchestrator.py`

实施要求：

- MCP result 返回后优先读取 `result.control_flow`；
- `SUCCESS`：保存 evidence，发送 `mcp_tool_result`，继续 structured `next_step`；
- `BLOCKED`：调用 policy 决策，阈值内 `await sleep` 并重试同一 tool/args；
- `RETRYABLE_ERROR`：阈值内自动重试，超限发送 recoverable error；
- `NEEDS_USER_INPUT`：创建 pending input，发送 `user_input_required`；
- `FATAL_ERROR`：发送 unrecoverable error，标记 step failed；
- 所有 SSE payload 带 `control_flow`。

依赖：T2.4、T3.2。

验收：

- 不再从 `result.text` 判断 blocked/error/user input；
- 自动重试不会无限循环；
- retry 同一 tool 与同一 args；
- `operation_id` 用于 retry state key。

#### T3.4 新增 SSE 事件

范围：

- `agent-service/src/api/sse.py`
- Orchestrator event emission code。

新增事件：

- `control_flow_waiting`
- `control_flow_retrying`

扩展事件：

- `mcp_tool_result` 增加 `control_flow`、`data`、`retry_attempt`；
- `user_input_required` 增加 `control_flow`、`required_inputs`；
- `error` 增加 `control_flow`。

依赖：T3.3。

验收：

- 前端收到 `BLOCKED` 时至少能看到 `mcp_tool_result` 与 `control_flow_waiting`；
- `FATAL_ERROR / MCP_PROTOCOL_ERROR` 的 error SSE 带标准 control flow。

#### T3.5 PendingInput 映射改造

范围：

- `agent-service/src/core/orchestrator.py`
- `PendingInput` 构造逻辑。

实施要求：

- `required_inputs` 单字段映射为 path/text；
- 多字段映射为 params/json；
- options 映射为 choice；
- confirmation 映射为 confirm；
- metadata 保存 `control_flow`、`required_inputs`、`tool_name`、`resolved_args`、`retry_state`。

依赖：T3.3。

验收：

- `NEEDS_USER_INPUT` 能暂停；
- 用户 continue 后能 merge args 并继续原 MCP tool。

#### T3.6 Agent Orchestrator 测试

建议新增或扩展：

- `agent-service/tests/test_orchestrator_control_flow.py`

覆盖：

- `SUCCESS -> next_step`；
- `BLOCKED -> auto retry -> SUCCESS`；
- `BLOCKED` 超限不无限循环；
- `RETRYABLE_ERROR -> retry -> SUCCESS`；
- `RETRYABLE_ERROR` 超限；
- `FATAL_ERROR` 不重试；
- `NEEDS_USER_INPUT` 触发 pending input；
- `MCP_PROTOCOL_ERROR` 发送 error。

依赖：T3.1-T3.5。

验收命令：

```bash
cd agent-service
pytest tests/test_orchestrator_control_flow.py tests/test_dynamic_mcp_orchestration.py -v
```

---

## 8. Phase 4：agent-web 结构化渲染落地

### 8.1 目标

让前端根据 `control_flow.status` / `reason` 渲染等待、重试、输入、错误组件，并接入新增 SSE 事件。

### 8.2 任务

#### T4.1 新增 TypeScript 类型

范围：

- `agent-web/src/types/index.ts`

新增：

- `ControlFlowStatus`
- `ControlFlowReason`
- `RequiredInput`
- `ControlFlow`
- `ControlFlowWaitingData`
- `ControlFlowRetryingData`

扩展：

- `SSEEventType` 增加 `control_flow_waiting`、`control_flow_retrying`；
- `UserInputRequiredData` 增加 `required_inputs`、`control_flow`；
- `ErrorData` 增加 `control_flow`。

依赖：T3.4 payload 定稿。

验收：

- TypeScript 类型能表达所有新增 SSE payload。

#### T4.2 修复 SSE parser chunk 边界问题

范围：

- `agent-web/src/services/api.ts`

实施要求：

- 将 `currentEvent`、`dataLines`、`currentId` 提升到 chunk 循环外；
- `remaining` 只保存不完整行；
- 空行才 finalize event；
- 支持 event line 与 data line 分处不同 chunk。

依赖：无，可独立做。

验收：

- 新增 parser 单元测试覆盖 chunk 分裂：
  - `event:` 与 `data:` 分裂；
  - JSON data 跨 chunk；
  - 多个事件同 chunk。

#### T4.3 新增 ControlFlow UI 组件

建议目录：

```text
agent-web/src/components/control-flow/
  ControlFlowCard.tsx
  WaitingStatusCard.tsx
  RetryStatusCard.tsx
  RequiredInputsForm.tsx
  FatalErrorCard.tsx
```

实现范围：

- `BLOCKED / WAITING_FOR_EVENT`：spinner + 等待事件 + 倒计时；
- `BLOCKED / RESOURCE_UNAVAILABLE`：资源准备中；
- `RETRYABLE_ERROR`：临时失败 + 自动重试提示；
- `NEEDS_USER_INPUT`：基础输入表单；
- `FATAL_ERROR`：错误卡片。

依赖：T4.1。

验收：

- 不依赖 Markdown 文本判断状态；
- `reason` 未匹配时 fallback 到 `user_message`；
- `MCP_PROTOCOL_ERROR` 有系统错误文案。

#### T4.4 改造 ChatView SSE 处理

范围：

- `agent-web/src/components/ChatView.tsx`
- store 如需新增状态则改造 `agent-web/src/stores/index.ts`

实施要求：

- `control_flow_waiting`：添加 trace，展示 waiting card；
- `control_flow_retrying`：添加 trace，展示 retry card；
- `mcp_tool_result` 非 `SUCCESS`：添加 control flow UI 状态；
- `user_input_required`：优先使用 `required_inputs` 渲染；
- `error`：若带 `control_flow`，使用 FatalErrorCard 或 error alert。

依赖：T4.3。

验收：

- BLOCKED 时 UI 有等待提示；
- NEEDS_USER_INPUT 时 UI 有输入入口；
- FATAL_ERROR 时 UI 有明确错误卡片。

#### T4.5 前端测试

建议覆盖：

- SSE parser chunk 边界；
- `control_flow_waiting` 渲染；
- `control_flow_retrying` 渲染；
- `NEEDS_USER_INPUT` 表单；
- `FATAL_ERROR / MCP_PROTOCOL_ERROR` 错误卡片。

依赖：T4.1-T4.4。

验收命令：

```bash
cd agent-web
npm run lint
npm run build
```

如项目有测试框架，再运行对应测试命令。

---

## 9. Phase 5：端到端验证与回归

### 9.1 目标

验证 MCP、Agent、Web 三端围绕结构化控制流形成闭环。

### 9.2 任务

#### T5.1 构建 mock MCP 或测试 playbook

覆盖场景：

1. `SUCCESS`；
2. `BLOCKED -> SUCCESS`；
3. `BLOCKED` 超限暂停；
4. `RETRYABLE_ERROR -> SUCCESS`；
5. `RETRYABLE_ERROR` 超限；
6. `NEEDS_USER_INPUT -> continue -> SUCCESS`；
7. `FATAL_ERROR`；
8. 非法 MCP response -> `MCP_PROTOCOL_ERROR`。

依赖：Phase 1、Phase 3。

验收：

- 每个场景都能通过 backend 测试或手工流式调用复现。

#### T5.2 后端端到端流式测试

范围：

- `POST /api/stream/message`
- `POST /api/stream/continue`

验证事件序列：

- `message_start`
- `mcp_tool_start`
- `mcp_tool_result`
- `control_flow_waiting` / `control_flow_retrying` / `user_input_required` / `error`
- `analysis_result` 或 `message_end`

依赖：T5.1。

验收：

- SSE event 顺序合理；
- event payload 包含 `control_flow`；
- 不出现无限等待。

#### T5.3 前端手工联调

手工验证：

- 发起诊断；
- 看到 MCP 工具开始；
- BLOCKED 时展示等待；
- retry 后成功继续；
- NEEDS_USER_INPUT 时输入参数；
- FATAL_ERROR 时展示错误。

依赖：Phase 4、T5.2。

验收：

- 前端不依赖文本 `BLOCKED:`；
- 用户可理解当前是等待、重试、需要输入还是错误。

#### T5.4 全量回归

运行：

```bash
cd mcp_service_code/ms_mcp
python -m pytest tests/ -v

cd ../../agent-service
pytest tests/ -v

cd ../agent-web
npm run lint
npm run build
```

依赖：所有开发任务完成。

验收：

- MCP 测试通过；
- Agent 测试通过；
- 前端 lint/build 通过；
- 若存在失败，记录失败原因并判断是否与本功能相关。

---

## 10. 里程碑与完成标准

### Milestone 1：MCP 契约完成

完成任务：

- T1.1-T1.6

完成标准：

- `execute_profiler_tool` 所有主路径都有 `control_flow`；
- MCP 单元测试覆盖核心状态；
- 不再输出用于机器解析的 Markdown `BLOCKED:`。

### Milestone 2：Agent 解析完成

完成任务：

- T2.1-T2.5

完成标准：

- `MCPGateway.execute_profiler_tool()` 返回 `ControlFlow`；
- 缺失/非法 `control_flow` 归一化为 `MCP_PROTOCOL_ERROR`；
- `next_step` 从结构化字段读取。

### Milestone 3：Agent 控制流完成

完成任务：

- T3.1-T3.6

完成标准：

- `SUCCESS` 继续；
- `BLOCKED` 阈值内自动等待重试；
- `RETRYABLE_ERROR` 可重试；
- `FATAL_ERROR` 不重试；
- `NEEDS_USER_INPUT` 暂停并可继续；
- SSE 带结构化 payload。

### Milestone 4：前端渲染完成

完成任务：

- T4.1-T4.5

完成标准：

- 前端展示等待、重试、输入、错误状态；
- 不依赖 Markdown 文本判断；
- SSE parser 对 chunk 边界稳定。

### Milestone 5：E2E 闭环完成

完成任务：

- T5.1-T5.4

完成标准：

- 覆盖 demo 主流程；
- 覆盖协议错误；
- 三端测试/构建通过。

---

## 11. 质量门禁

### 11.1 代码门禁

- 不新增直接调用 MCP 内部工具的 Agent 代码；
- Agent 仍必须通过 `MCPGateway` 调用 meta-tools；
- 不新增基于 Markdown `BLOCKED:` / `ERROR:` 的流程判断；
- 所有新增状态枚举必须与需求文档一致；
- retry 必须有最大次数与总等待时间上限。

### 11.2 测试门禁

必须至少覆盖：

- MCP wrapper 输出契约；
- Agent parser 协议错误；
- Agent blocked auto retry；
- Agent needs user input；
- Agent fatal error；
- 前端 waiting/error/input UI。

### 11.3 用户体验门禁

- 用户能看懂系统是在等待还是失败；
- 自动等待期间有可见状态；
- 需要输入时问题清晰；
- 不可恢复错误不会伪装成可重试。

---

## 12. 风险控制

### 12.1 严格协议导致 demo 主流程中断

风险：

- 某些 MCP 内部工具未包装 `control_flow`，Agent 会视为协议错误。

控制：

- 先覆盖主 demo playbook；
- 对所有未覆盖工具添加通用 `wrap_success` fallback；
- 通过 MCP 测试快速暴露遗漏。

### 12.2 自动 retry 持续占用 SSE 连接

风险：

- `await sleep()` 会让当前 stream 保持连接。

控制：

- demo 阶段接受；
- 单次等待使用 `max_retry_after_ms` clamp；
- 总等待用 `max_total_wait_ms` 限制；
- 每次等待前发送 `control_flow_waiting`。

### 12.3 operation_id 不稳定

风险：

- Agent retry state 无法聚合同一异步任务。

控制：

- 对异步任务强制返回 `operation_id`；
- 对纯查询场景用 args hash fallback；
- 测试覆盖同参数多次调用不重复创建任务。

### 12.4 前端动态表单复杂度过高

风险：

- 完整 schema-driven form 超出 demo 范围。

控制：

- demo 阶段只做：text/path、choice、confirm、多字段 JSON textarea；
- 后续产品化再引入完整 JSON schema form。

---

## 13. 推荐执行顺序清单

按顺序执行：

1. T0.1 确认主 demo playbook 与内部工具路径；
2. T0.2 准备 mock MCP 响应样例；
3. T1.1 定义 MCP wrapper；
4. T1.2 改造 MCP execute 统一出口；
5. T1.3-T1.5 映射 blocked / input / error；
6. T1.6 MCP 单元测试；
7. T2.1 新增 Agent ControlFlow 模型；
8. T2.2 扩展 MCPToolResult；
9. T2.3 改造 MCPResponseParser；
10. T2.4 改造 MCPGateway；
11. T2.5 Agent parser/gateway 测试；
12. T3.1 新增 control_flow 配置；
13. T3.2 扩展 InteractionPolicy；
14. T3.3 改造 `_execute_mcp_chain()`；
15. T3.4 新增/扩展 SSE 事件；
16. T3.5 改造 PendingInput 映射；
17. T3.6 Agent orchestrator 测试；
18. T4.1 新增前端类型；
19. T4.2 修复 SSE parser；
20. T4.3 新增 ControlFlow UI 组件；
21. T4.4 改造 ChatView；
22. T4.5 前端测试；
23. T5.1 构建 mock MCP 或测试 playbook；
24. T5.2 后端流式 E2E；
25. T5.3 前端手工联调；
26. T5.4 全量回归。

---

## 14. 下一步

该工作流完成后，下一步应使用 `/sc:implement` 按阶段实施。

建议优先从最小闭环开始：

1. MCP 统一包装 `SUCCESS` / `BLOCKED` / `NEEDS_USER_INPUT` / `FATAL_ERROR`；
2. Agent 严格解析 `control_flow`；
3. Orchestrator 支持 `BLOCKED` 自动重试 3 次；
4. 前端展示等待卡片与输入表单；
5. 用一个 mock playbook 完成 E2E 验证。

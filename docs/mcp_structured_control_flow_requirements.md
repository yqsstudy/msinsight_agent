# MCP 结构化流程控制 (Structured Control Flow) 需求说明书

## 1. 背景与目的

当前底层 `ms_mcp` 服务在遇到耗时操作或异步事件未就绪时（例如等待 `clusterCompleted` 事件），主要通过 Markdown 文本中类似 `BLOCKED: 等待聚类完成` 的字符串告知上层 `agent-service`。

这种纯文本控制流存在以下问题：

- **脆弱性 (Brittle)**：文案、大小写、格式或语言的微小变化都可能导致上层正则/字符串匹配失效。
- **缺乏语义 (Lack of Semantics)**：上层 Orchestrator 无法稳定区分“等待事件”“资源未就绪”“临时错误”“需要用户输入”等不同控制状态。
- **不利于自动编排**：上层难以基于确定性状态实现自动等待、自动重试、防死锁、暂停恢复或用户介入。
- **用户体验不佳**：前端无法根据结构化原因渲染等待、倒计时、重试、错误或输入组件。

**目的**：为 `ms_mcp` 返回给 `agent-service` 的工具执行结果定义一套严格的 JSON 结构化控制流契约，使上层 Agent 能通过确定性的状态码和原因码进行流程阻断、自动等待、自动重试、用户输入请求和错误降级。

本需求面向当前 demo 阶段设计，**不考虑旧协议兼容**。

---

## 2. 核心原则

### 2.1 所有响应必须包含 `control_flow`

`ms_mcp` 通过 `execute_profiler_tool` 返回给 `agent-service` 的所有工具执行结果，必须在结构化 JSON 返回体中包含 `control_flow` 对象。

即使工具成功执行并返回最终结果，也必须包含：

```json
{
  "control_flow": {
    "status": "SUCCESS"
  },
  "data": {}
}
```

### 2.2 缺失或非法 `control_flow` 是协议错误

由于当前阶段不考虑兼容性，`agent-service` 不应将缺失 `control_flow` 的响应默认为成功。

若出现以下情况，应视为 MCP 协议错误：

- `result.raw` 中缺失 `control_flow`；
- `control_flow` 不是对象；
- `control_flow.status` 缺失；
- `status` 不在约定枚举中；
- 必填字段不满足当前 `status` / `reason` 的约束。

上层可将其归一化为：

```json
{
  "control_flow": {
    "status": "FATAL_ERROR",
    "reason": "MCP_PROTOCOL_ERROR",
    "retryable": false
  },
  "data": {
    "error": "Invalid MCP structured control_flow response"
  }
}
```

### 2.3 Markdown 不承载控制流语义

MCP 返回的 Markdown / text 内容只用于人类或 LLM 阅读，不作为 `agent-service` 的流程判断依据。

废弃旧模式：

```markdown
BLOCKED: 等待聚类完成
```

上层不得再通过如下方式判断流程状态：

```python
if "BLOCKED" in result.text:
    ...
```

正确方式是只读取：

```python
result.raw["control_flow"]["status"]
```

### 2.4 MCP 报告事实，Agent 决策策略

`ms_mcp` 不负责长时间自动轮询，也不在内部执行复杂自动重试策略。

`ms_mcp` 负责返回：

- 当前状态；
- 产生该状态的原因；
- 是否允许重试；
- 建议多久后重试；
- 等待的事件或资源；
- 当前异步操作标识。

`agent-service` 的 Orchestrator / InteractionPolicy 负责决策：

- 是否自动等待；
- 是否自动重试；
- 最多重试几次；
- 是否暂停流程并请求用户输入；
- 是否终止当前 playbook；
- 是否向前端发送等待、错误或输入类 SSE 事件。

### 2.5 前端根据结构化原因渲染

前端优先根据 `status`、`reason`、`event_name`、`suggested_retry_after_ms` 等结构化字段渲染 UI。

`user_message` 可作为兜底文案或调试辅助，但不作为主要交互协议。

---

## 3. 数据契约

### 3.1 顶层结构

所有工具执行结果的结构化 JSON 返回体必须符合以下形态：

```json
{
  "control_flow": {
    "status": "SUCCESS"
  },
  "data": {
    "...": "业务数据"
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `control_flow` | object | 是 | 结构化流程控制对象。 |
| `data` | object | 是 | 业务数据、分析结果或错误详情。无业务数据时使用空对象 `{}`。 |

### 3.2 `control_flow` 字段

| 字段名 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `status` | string | 是 | 流程控制状态。必须使用本文档定义的枚举值。 |
| `reason` | string | 条件必填 | 状态原因。除 `SUCCESS` 外建议必填。 |
| `retryable` | boolean | 条件必填 | 当前响应是否允许上层自动重试。`BLOCKED` / `RETRYABLE_ERROR` 必填。 |
| `suggested_retry_after_ms` | integer | 条件必填 | 建议上层等待多久后重试，单位毫秒。`retryable = true` 时建议必填。 |
| `event_name` | string | 条件必填 | 等待的事件名。`reason = WAITING_FOR_EVENT` 时必填。 |
| `operation_id` | string | 条件必填 | 异步操作 ID。`BLOCKED` 且涉及异步操作时必填。 |
| `required_inputs` | array | 条件必填 | 需要用户补充的输入项。`status = NEEDS_USER_INPUT` 时必填。 |
| `message_params` | object | 否 | 前端模板渲染参数，例如预计等待秒数。 |
| `user_message` | string | 否 | 兜底用户提示文案。前端优先根据结构化字段渲染。 |
| `developer_message` | string | 否 | 面向开发者或日志排查的说明，不建议直接展示给终端用户。 |

---

## 4. 状态枚举

### 4.1 `SUCCESS`

表示当前工具调用已经成功完成，上层可以继续执行 playbook 的下一步。

最小响应：

```json
{
  "control_flow": {
    "status": "SUCCESS"
  },
  "data": {
    "summary": "分析完成"
  }
}
```

Agent 行为：

- 读取 `data` 中的业务结果；
- 继续执行 MCP 返回的 `next_step`；
- 若无下一步，则完成当前诊断流程。

### 4.2 `BLOCKED`

表示当前工具调用没有失败，但依赖的异步事件、资源或后台任务尚未就绪。

典型场景：

- 等待 `clusterCompleted` 事件；
- 等待 profiling 文件解析完成；
- 等待 timeline / cluster / memory 数据生成完成。

示例：

```json
{
  "control_flow": {
    "status": "BLOCKED",
    "reason": "WAITING_FOR_EVENT",
    "event_name": "clusterCompleted",
    "operation_id": "cluster-op-123",
    "retryable": true,
    "suggested_retry_after_ms": 5000,
    "message_params": {
      "seconds": 5
    }
  },
  "data": {}
}
```

Agent 行为：

- 若 `retryable = true`，由 Orchestrator / InteractionPolicy 判断是否自动等待并重试；
- 自动重试次数、总等待时间、防死锁阈值由 `agent-service` 策略控制；
- 若超过自动重试阈值，可向前端发送等待状态或请求用户手动重试；
- 不应将 `BLOCKED` 视为失败。

### 4.3 `RETRYABLE_ERROR`

表示当前工具调用发生临时错误，但理论上可以稍后重试。

典型场景：

- 后端服务临时不可用；
- 网络抖动；
- 临时超时；
- 被限流。

示例：

```json
{
  "control_flow": {
    "status": "RETRYABLE_ERROR",
    "reason": "RATE_LIMITED",
    "retryable": true,
    "suggested_retry_after_ms": 3000
  },
  "data": {
    "error": "backend rate limited"
  }
}
```

Agent 行为：

- 可根据策略自动等待并重试；
- 超过重试阈值后，应转为用户可见错误或降级路径；
- 与 `BLOCKED` 的区别是：`RETRYABLE_ERROR` 表示发生了异常，`BLOCKED` 表示预期内的等待。

### 4.4 `FATAL_ERROR`

表示当前工具调用发生不可恢复错误，继续重试通常没有意义。

典型场景：

- 参数非法；
- 文件不存在；
- profile 数据格式不支持；
- playbook 配置错误；
- MCP 返回体不符合协议。

示例：

```json
{
  "control_flow": {
    "status": "FATAL_ERROR",
    "reason": "INVALID_PARAMETER",
    "retryable": false
  },
  "data": {
    "error": "profile_path is invalid"
  }
}
```

Agent 行为：

- 不自动重试；
- 终止当前工具步骤或当前 playbook；
- 向前端发送错误事件；
- 根据错误原因决定是否允许用户修改参数后重新发起。

### 4.5 `NEEDS_USER_INPUT`

表示当前流程必须等待用户补充信息、做出选择或确认操作。

典型场景：

- 缺少必要参数；
- 需要用户选择 rank / device / profile；
- 需要用户确认有副作用操作；
- 需要用户上传或指定文件。

示例：

```json
{
  "control_flow": {
    "status": "NEEDS_USER_INPUT",
    "reason": "MISSING_REQUIRED_PARAMETER",
    "retryable": false,
    "required_inputs": [
      {
        "name": "profile_path",
        "type": "string",
        "description": "请提供 profiling 数据路径"
      }
    ]
  },
  "data": {}
}
```

Agent 行为：

- 暂停当前流程；
- 将 `required_inputs` 转换为 `PendingInput` 或等价结构；
- 通过 `user_input_required` SSE 事件通知前端；
- 用户补充信息后再继续流程。

---

## 5. `reason` 枚举

当前 demo 阶段定义以下原因码：

| reason | 适用 status | 含义 |
| :--- | :--- | :--- |
| `WAITING_FOR_EVENT` | `BLOCKED` | 正在等待特定异步事件。 |
| `RESOURCE_UNAVAILABLE` | `BLOCKED` / `RETRYABLE_ERROR` | 依赖资源尚未准备好或暂不可用。 |
| `RATE_LIMITED` | `RETRYABLE_ERROR` | 请求被限流，可稍后重试。 |
| `MISSING_REQUIRED_PARAMETER` | `NEEDS_USER_INPUT` / `FATAL_ERROR` | 缺少必要参数。若可由用户补充，使用 `NEEDS_USER_INPUT`。 |
| `USER_CONFIRMATION_REQUIRED` | `NEEDS_USER_INPUT` | 需要用户确认后才能继续。 |
| `INVALID_PARAMETER` | `FATAL_ERROR` | 参数存在但非法，无法继续。 |
| `BACKEND_ERROR` | `RETRYABLE_ERROR` / `FATAL_ERROR` | 后端服务错误。是否可重试由 `status` 和 `retryable` 决定。 |
| `TIMEOUT` | `RETRYABLE_ERROR` / `FATAL_ERROR` | 调用超时。是否可重试由 `status` 和 `retryable` 决定。 |
| `MCP_PROTOCOL_ERROR` | `FATAL_ERROR` | MCP 返回体不符合结构化控制流协议。 |

`reason` 不应使用任意自由文本。若需要新增原因码，应更新本文档和对应解析逻辑。

---

## 6. 自动重试与幂等约束

### 6.1 自动重试由 Agent 决策

MCP 只通过以下字段提供建议：

```json
{
  "retryable": true,
  "suggested_retry_after_ms": 5000
}
```

是否实际自动重试由 `agent-service` 决定。

建议 `agent-service` 配置类似策略：

```yaml
control_flow:
  max_auto_retries: 3
  max_total_wait_ms: 30000
```

### 6.2 `retryable = true` 的含义

当 MCP 返回 `retryable = true` 时，表示 MCP 承诺：上层在建议时间后重复调用该步骤是安全的。

这里的“安全”至少意味着：

- 不会重复创建多个后台任务；
- 不会重复写入或覆盖关键数据；
- 不会重复删除资源；
- 不会因为重复调用导致 playbook 状态错乱；
- 重复调用要么检查同一个异步操作，要么返回同一类稳定结果。

### 6.3 幂等解释

幂等是指：同一个操作使用相同参数执行一次或多次，对系统产生的最终效果相同。

适合自动重试的幂等操作：

- 查询某个异步任务是否完成；
- 获取某个 profile 的分析结果；
- 检查某个事件是否到达；
- 读取已经生成的 timeline / cluster / memory 数据。

不适合直接自动重试的非幂等操作：

- 启动新的后台分析任务；
- 创建新报告；
- 写入 case library；
- 删除缓存或文件；
- 修改全局状态。

如果某个工具第一次调用会启动异步任务，后续重试必须通过 `operation_id` 绑定到同一个任务，避免重复启动。

---

## 7. 异步操作标识

### 7.1 `operation_id`

对于 `BLOCKED` 且 `reason = WAITING_FOR_EVENT` 的响应，MCP 应返回 `operation_id`。

`operation_id` 用于标识底层正在等待的具体异步操作，例如：

```json
{
  "operation_id": "cluster-op-123"
}
```

它解决的问题是：当多个 session、多个 profile、多个 playbook 步骤同时等待同名事件时，上层能够知道当前等待的是哪一个具体操作。

例如，仅返回：

```json
{
  "event_name": "clusterCompleted"
}
```

不足以区分：

- 是哪个 profile 的聚类完成事件；
- 是哪个 session 发起的操作；
- 是哪个 playbook step 阻塞；
- 后续重试应检查哪个后台任务。

因此推荐完整表达为：

```json
{
  "control_flow": {
    "status": "BLOCKED",
    "reason": "WAITING_FOR_EVENT",
    "event_name": "clusterCompleted",
    "operation_id": "cluster-op-123",
    "retryable": true,
    "suggested_retry_after_ms": 5000
  },
  "data": {}
}
```

### 7.2 `correlation_id`

`correlation_id` 用于链路追踪和日志排查，例如关联用户会话、playbook step、MCP 调用和后端事件。

demo 阶段暂不强制引入 `correlation_id`。若现有系统已有 session id、step id 或 trace id，可在日志和 SSE 事件中复用现有标识。

---

## 8. 上下层交互时序

### 8.1 成功路径

1. `agent-service` 调用 `execute_profiler_tool`。
2. `ms_mcp` 执行工具并返回：

   ```json
   {
     "control_flow": {
       "status": "SUCCESS"
     },
     "data": {
       "summary": "分析完成"
     }
   }
   ```

3. `agent-service` 读取 `control_flow.status = SUCCESS`。
4. Orchestrator 继续执行 MCP 返回的后续步骤，或结束当前流程。

### 8.2 阻塞与自动重试路径

1. `agent-service` 调用 `execute_profiler_tool`。
2. `ms_mcp` 检测到依赖事件未完成，返回：

   ```json
   {
     "control_flow": {
       "status": "BLOCKED",
       "reason": "WAITING_FOR_EVENT",
       "event_name": "clusterCompleted",
       "operation_id": "cluster-op-123",
       "retryable": true,
       "suggested_retry_after_ms": 5000
     },
     "data": {}
   }
   ```

3. `agent-service` 读取结构化控制流。
4. InteractionPolicy / Orchestrator 检查自动重试次数和总等待时间。
5. 如果仍在阈值内，后台等待 `suggested_retry_after_ms` 后重试同一操作。
6. 如果超出阈值，向前端发送等待状态或请求用户手动重试。
7. 后续重试返回 `SUCCESS` 后，流程继续。

### 8.3 需要用户输入路径

1. MCP 返回：

   ```json
   {
     "control_flow": {
       "status": "NEEDS_USER_INPUT",
       "reason": "MISSING_REQUIRED_PARAMETER",
       "retryable": false,
       "required_inputs": [
         {
           "name": "profile_path",
           "type": "string",
           "description": "请提供 profiling 数据路径"
         }
       ]
     },
     "data": {}
   }
   ```

2. `agent-service` 暂停当前流程。
3. `agent-service` 将 `required_inputs` 转换为上层 pending input 结构。
4. 通过 `user_input_required` SSE 事件通知前端。
5. 用户补充信息后，`agent-service` 继续原流程。

### 8.4 协议错误路径

1. MCP 返回缺失或非法 `control_flow` 的响应。
2. `agent-service` 将其视为 `MCP_PROTOCOL_ERROR`。
3. 当前工具步骤失败，不做 Markdown fallback。
4. 前端展示协议错误或系统错误。

---

## 9. 前端渲染要求

前端不应直接依赖 MCP 自然语言文案判断状态，而应根据结构化字段渲染。

建议映射：

| status | reason | UI 行为 |
| :--- | :--- | :--- |
| `BLOCKED` | `WAITING_FOR_EVENT` | Spinner + 等待事件完成 + 可选倒计时。 |
| `BLOCKED` | `RESOURCE_UNAVAILABLE` | Spinner + 资源准备中提示。 |
| `RETRYABLE_ERROR` | `RATE_LIMITED` | 倒计时重试或稍后重试提示。 |
| `RETRYABLE_ERROR` | `TIMEOUT` | 临时失败提示 + 自动/手动重试。 |
| `NEEDS_USER_INPUT` | `MISSING_REQUIRED_PARAMETER` | 展示参数输入表单。 |
| `NEEDS_USER_INPUT` | `USER_CONFIRMATION_REQUIRED` | 展示确认按钮或确认弹窗。 |
| `FATAL_ERROR` | `INVALID_PARAMETER` | 错误卡片 + 参数修改建议。 |
| `FATAL_ERROR` | `MCP_PROTOCOL_ERROR` | 系统错误提示。 |

`user_message` 仅用于：

- 没有匹配到前端模板时的兜底展示；
- debug / demo 快速展示；
- 日志记录辅助。

---

## 10. 实施边界

### 10.1 MCP 服务端

需要在 `ms_mcp` 的统一工具执行出口或相关 decorator 中完成结构化包装。

重点包括：

- 所有成功响应包装 `control_flow.status = SUCCESS`；
- 等待事件时返回 `BLOCKED / WAITING_FOR_EVENT`；
- 临时错误返回 `RETRYABLE_ERROR`；
- 不可恢复错误返回 `FATAL_ERROR`；
- 需要用户补充信息时返回 `NEEDS_USER_INPUT`；
- 不再依赖 Markdown 中的 `BLOCKED:` 文本作为协议。

### 10.2 Agent Orchestrator 端

需要调整 `agent-service` 的 MCP 结果解析和流程仲裁逻辑。

重点包括：

- 只读取 `result.raw.control_flow` 进行流程判断；
- 缺失或非法 `control_flow` 直接视为协议错误；
- 根据 `status` 和 `reason` 分派到继续执行、自动等待、自动重试、用户输入、终止流程等路径；
- 自动重试次数和总等待时间由 Agent 策略控制；
- 不再解析 Markdown `BLOCKED:` 文本。

### 10.3 前端面板

需要增加结构化控制流状态的 UI 渲染。

重点包括：

- 等待状态展示；
- 倒计时或重试按钮；
- 用户输入表单；
- 可重试错误提示；
- 不可恢复错误提示；
- 根据 `reason` 映射标准文案和组件。

---

## 11. 验收标准

### 11.1 MCP 响应契约

- 所有工具成功响应均包含 `control_flow.status = SUCCESS`。
- 所有阻塞响应均包含 `status = BLOCKED`、`reason`、`retryable`。
- `reason = WAITING_FOR_EVENT` 时必须包含 `event_name`。
- 涉及异步操作的 `BLOCKED` 响应必须包含 `operation_id`。
- `NEEDS_USER_INPUT` 响应必须包含 `required_inputs`。
- 不再输出用于机器解析的 Markdown `BLOCKED:` 协议文本。

### 11.2 Agent 行为

- `agent-service` 不通过 `result.text` 判断阻塞或错误状态。
- 缺失 `control_flow` 的响应被识别为 `MCP_PROTOCOL_ERROR`。
- `SUCCESS` 响应继续执行后续步骤。
- `BLOCKED + retryable = true` 在策略阈值内触发自动等待/重试。
- 自动重试超过阈值后不会无限循环。
- `RETRYABLE_ERROR` 可按策略重试。
- `FATAL_ERROR` 不自动重试。
- `NEEDS_USER_INPUT` 会触发 `user_input_required` SSE 事件。

### 11.3 前端行为

- 前端能根据 `BLOCKED / WAITING_FOR_EVENT` 展示等待状态。
- 前端能根据 `suggested_retry_after_ms` 展示倒计时或重试提示。
- 前端能根据 `NEEDS_USER_INPUT` 展示输入表单。
- 前端能区分可重试错误与不可恢复错误。
- 前端不依赖 Markdown 文本中的 `BLOCKED:` 判断 UI 状态。

---

## 12. 非目标

当前 demo 阶段不包含以下目标：

- 兼容旧 MCP 响应协议；
- fallback 到 Markdown 文本匹配；
- 完整国际化文案系统；
- 复杂分布式 tracing 设计；
- MCP 内部长轮询或复杂自动重试；
- 完整 idempotency key 体系。

这些能力可在后续产品化阶段基于本结构化控制流契约扩展。

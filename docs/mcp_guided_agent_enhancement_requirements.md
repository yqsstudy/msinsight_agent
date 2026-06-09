# 需求文档：MCP 约束下的智能诊断 Agent 增强

## 1. 背景

当前系统采用 **MCP 元工具模式** 进行性能诊断编排：

- Agent Service 只通过 MCP Gateway 调用元工具：
  - `search_profiler_tools`
  - `execute_profiler_tool`
- MCP Server 负责 playbook 导航、工具依赖、`next_step` 引导和流程状态维护。
- 每一步工具通过 schema / Pydantic 进行参数校验。
- LLM 目前主要用于：
  - playbook 搜索 query 改写；
  - playbook 选择/排序；
  - schema 限定的参数抽取；
  - 部分用户输入辅助。

该架构保证了流程可控、工具合法、参数可校验，但在实际交互中暴露出一些体验和可诊断性问题。

---

## 2. 当前问题

### 2.1 LLM 辅助失败日志不可诊断

当前日志示例：

```text
LLM assistance failed at extract_parameters_by_schema: TimeoutError:
LLM assistance failed at parameter_extraction: TimeoutError:
```

问题：

- `TimeoutError` 后没有具体异常信息；
- 不知道超时时间；
- 不知道调用的 provider / model；
- 不知道当前处理的是哪个工具；
- 不知道 required 参数有哪些；
- 不知道失败后进入了什么 fallback；
- 难以判断是模型慢、网络问题、prompt 过长，还是 provider 异常。

---

### 2.2 历史参数没有正确继承

在某些 MCP playbook 步骤中，下一步工具 schema 要求：

```json
{
  "required": ["iterationId", "groupIdHash"]
}
```

但其中 `iterationId` 已经在前序 MCP 调用或当前诊断上下文中存在。

当前问题是：

- Agent 在进入下一步参数解析时，没有稳定继承历史上下文中的 `iterationId`；
- LLM 参数抽取超时后，deterministic fallback 也没有成功补上该参数；
- 最终误判 `iterationId` 和 `groupIdHash` 都缺失；
- 前端显示：

```text
下一步 `communication_duration_slow_rank_list` 需要参数：iterationId, groupIdHash。请补充参数。
```

这会让用户误以为两个参数都需要手动输入。

---

### 2.3 候选参数没有传递给前端

前序 MCP 工具已经返回了可供用户选择的通信组信息，例如：

```json
{
  "data": [
    {
      "groupIdHash": "mock_group_hash",
      "pgName": "mock_pg",
      "duration": 120.5,
      "rankList": ["0", "1"]
    }
  ]
}
```

按业务逻辑，下一步应该提示用户选择要继续分析的通信组：

```text
请选择要分析的通信组。
```

并展示选项：

```text
mock_pg / mock_group_hash / 120.5ms / ranks: 0,1
```

但当前前端没有收到候选项，只能展示通用缺参提示。

---

### 2.4 用户提示过于机械

当前提示大概率由后端固定模板生成：

```text
下一步 `communication_duration_slow_rank_list` 需要参数：iterationId, groupIdHash。请补充参数。
```

该提示不是 AI 生成的，而是基于：

- `next_step.tool_name`
- `next_step.schema.required`
- 当前缺失参数列表

拼接出来。

问题：

- 不解释为什么需要这些参数；
- 不说明哪些参数已从上下文继承；
- 不说明用户当前真正需要做什么；
- 不展示候选项含义；
- 不利于非研发用户理解诊断流程。

---

### 2.5 LLM 使用能力偏弱

当前 Agent 设计偏向 deterministic orchestrator，LLM 主要作为辅助抽参模块。

但在当前 MCP 架构下，已经具备：

- 元工具边界；
- playbook 控制；
- `next_step` 引导；
- Pydantic/schema 强校验；
- MCP 端依赖控制；
- Agent 端 interaction policy。

因此可以考虑适度增强 LLM 能力，让其在受约束范围内承担更多上下文理解、参数绑定解释、候选项说明和用户提示生成工作。

---

## 3. 目标

### 3.1 短期目标

修复当前暴露的两个关键问题：

1. 增强 LLM 辅助失败日志，使 timeout 和异常可诊断；
2. 修复下一步参数解析和用户输入提示：
   - 正确继承历史 `iterationId`；
   - 只向用户请求真正缺失的 `groupIdHash`；
   - 将上一步 MCP 结果中的通信组选项传给前端。

---

### 3.2 中期目标

在不破坏 MCP 元工具模式的前提下，增强 Agent 的智能性：

- 引入 MCP 约束下的上下文推理能力；
- 让 LLM 在 `next_step`、schema、候选参数和 interaction policy 限制内进行辅助决策；
- 改善用户提示质量；
- 支持候选项解释、推荐和确认；
- 保持工具调用可控、参数可校验、流程可追踪。

---

### 3.3 长期目标

形成一种 **MCP-constrained intelligent orchestrator**，即：

```text
MCP 负责流程权威性
Schema/Pydantic 负责参数合法性
Agent Service 负责状态编排和交互策略
LLM 负责上下文理解、参数辅助、提示生成和结果解释
```

避免退回传统自由 ReAct，采用受 MCP 约束的 Guided ReAct / Bounded ReAct 模式。

---

## 4. 范围

### 4.1 本阶段包含

本阶段需求聚焦以下内容：

1. LLM 辅助日志增强；
2. 历史参数继承；
3. 候选参数提取；
4. `user_input_required` 事件增强；
5. 前端展示字段级候选项；
6. 用户提示文案优化；
7. 受约束 LLM 能力增强的需求定义。

---

### 4.2 本阶段不包含

以下内容暂不纳入本阶段：

1. 不修改 MCP Server 当前 `data.text` 混合 markdown/JSON 的返回方式；
2. 不要求 MCP 响应全面重构为纯结构化 JSON；
3. 不开放 LLM 自由选择任意 profiler tool；
4. 不允许 LLM 绕过 MCP `next_step`；
5. 不实现传统自由 ReAct agent；
6. 不改变 MCP 元工具暴露方式；
7. 不新增顶层 MCP 工具；
8. 不重新设计整个 playbook 系统。

---

## 5. 用户与角色

### 5.1 终端用户

使用自然语言进行性能诊断的用户。

需求：

- 能理解当前诊断进展；
- 能看到下一步要做什么；
- 能通过选择项继续分析；
- 不需要手动填写系统已经知道的参数；
- 不需要理解 `groupIdHash` 等内部字段的来源细节。

---

### 5.2 诊断系统开发者

维护 agent-service、MCP service 和前端的人。

需求：

- 能从日志中判断 LLM 调用失败原因；
- 能追踪参数来源；
- 能确认是用户缺参、上下文丢失，还是 LLM timeout；
- 能测试每一步参数解析和交互暂停逻辑。

---

### 5.3 MCP Playbook 作者

维护 MCP 内部工具、metadata、playbook YAML 的人。

需求：

- MCP 仍然作为流程权威；
- Agent 不能绕过 playbook；
- 如果未来 MCP 增加候选参数输出，Agent 能消费；
- playbook 的 `next_step` 和 schema 仍然是下一步执行依据。

---

## 6. 功能需求

## FR-1：LLM 辅助失败日志增强

### 描述

当 LLM 辅助调用失败时，系统必须输出足够诊断的信息。

### 需求

系统在以下场景中必须增强日志：

- 参数抽取超时；
- 参数抽取返回非法 JSON；
- LLM provider 异常；
- LLM router 调用异常；
- LLM 响应不符合预期结构。

### 日志必须包含

- `stage`
- `exception_type`
- `exception_repr`
- `timeout_seconds`
- `elapsed_ms`
- `provider`
- `model`
- fallback 行为

如上下文可得，还应包含：

- `tool_name`
- `required_keys`
- `schema_keys`
- `session_id`
- `request_id`

### 验收标准

当发生 timeout 时，日志不应再是：

```text
TimeoutError:
```

而应类似：

```text
LLM assistance timeout at extract_parameters_by_schema: tool=communication_duration_slow_rank_list required=["iterationId","groupIdHash"] timeout_seconds=30 elapsed_ms=30012.45 provider=claude model=claude-sonnet-4-6 fallback=deterministic_parameter_resolution
```

---

## FR-2：历史参数继承

### 描述

当 MCP 下一步工具 schema 要求某个参数时，如果该参数已在历史上下文中存在，Agent 应自动继承，不应再次要求用户输入。

### 关键场景

当前步骤需要：

```json
["iterationId", "groupIdHash"]
```

但 `iterationId` 已在前序 MCP 调用中存在。

系统应最终判断：

```json
{
  "resolved_params": {
    "iterationId": "已有值"
  },
  "missing_required": ["groupIdHash"]
}
```

而不是：

```json
{
  "missing_required": ["iterationId", "groupIdHash"]
}
```

### 参数来源优先级

系统应支持清晰的参数合并优先级。

建议优先级：

1. 用户本轮显式输入；
2. 当前步骤已解析参数；
3. 上一步工具参数；
4. 上一步工具结构化输出；
5. session / playbook context；
6. deterministic extraction；
7. LLM 辅助抽取；
8. schema default。

### 限制

- 历史参数只能用于填充当前 schema 允许的字段；
- 不应将无关历史参数传给工具；
- 用户显式输入应优先于历史继承；
- 参数最终必须经过 schema/Pydantic 校验。

### 验收标准

当 `iterationId` 已存在时，前端不应提示用户补充 `iterationId`。

---

## FR-3：候选参数提取

### 描述

Agent 应能从上一步 MCP 工具结果中提取当前缺失参数的候选项。

### 关键场景

上一步返回：

```json
{
  "data": [
    {
      "groupIdHash": "mock_group_hash",
      "pgName": "mock_pg",
      "duration": 120.5,
      "rankList": ["0", "1"]
    }
  ]
}
```

下一步需要：

```json
{
  "required": ["groupIdHash"]
}
```

系统应生成候选项：

```json
[
  {
    "label": "mock_pg / mock_group_hash / 120.5ms / ranks: 0,1",
    "value": "mock_group_hash",
    "metadata": {
      "groupIdHash": "mock_group_hash",
      "pgName": "mock_pg",
      "duration": 120.5,
      "rankList": ["0", "1"]
    }
  }
]
```

### 候选项来源

候选项可来自：

- MCP structured result；
- produced params；
- known params；
- MCP `required_inputs.options`；
- 当前步骤 schema 中的 `enum` 或 `options`；
- 上一步结果中可识别的对象列表。

### 字段识别

对于 `groupIdHash`，系统应识别以下可能来源：

- `groupIdHash_options`
- `groupIdHashOptions`
- `groupIdHashList`
- `groupIdHashes`
- `group_id_hashes`
- `groups`
- `group_candidates`
- `candidate_inputs.groupIdHash`
- 对象列表中的 `groupIdHash` 字段

### 验收标准

当前端需要用户选择 `groupIdHash` 时，后端应提供可展示的 `options`。

---

## FR-4：字段级用户输入需求

### 描述

`user_input_required` 事件应支持字段级输入结构，而不是只有一段文本问题。

### 事件结构要求

后端应在 `user_input_required` 中提供：

```json
{
  "input_type": "params",
  "question": "下一步将定位通信阻塞的 Slow Rank。请选择要分析的通信组。",
  "metadata": {
    "tool_name": "communication_duration_slow_rank_list",
    "missing_required": ["groupIdHash"],
    "resolved_params": {
      "iterationId": "xxx"
    },
    "fields": [
      {
        "name": "groupIdHash",
        "label": "通信组",
        "type": "select",
        "required": true,
        "description": "Hash identifier of the communication group to analyze.",
        "options": [
          {
            "label": "mock_pg / mock_group_hash / 120.5ms / ranks: 0,1",
            "value": "mock_group_hash",
            "metadata": {
              "pgName": "mock_pg",
              "duration": 120.5,
              "rankList": ["0", "1"]
            }
          }
        ]
      }
    ]
  }
}
```

### 兼容要求

如果当前前端仍使用顶层 `options`，后端可在只有一个字段需要选择时同步提供：

```json
{
  "options": []
}
```

但新逻辑应优先使用：

```json
metadata.fields
```

### 验收标准

前端能通过 `metadata.fields` 判断：

- 哪些字段需要输入；
- 哪些字段可选择；
- 每个字段的候选项是什么；
- 哪些参数已经由后端自动解析。

---

## FR-5：前端字段级输入渲染

### 描述

前端应支持根据 `user_input_required.metadata.fields` 渲染用户输入表单。

### 渲染规则

字段存在 `options` 且非空时：

- 渲染为下拉框、单选列表或按钮选项；
- 展示 `label`；
- 提交 `value`。

字段没有 `options` 时：

- 渲染为文本输入框；
- 使用字段 `label` 和 `description` 提示用户。

### 提交格式

用户提交后，前端应发送参数对象：

```json
{
  "groupIdHash": "mock_group_hash"
}
```

如果后端要求多个字段，则发送：

```json
{
  "fieldA": "valueA",
  "fieldB": "valueB"
}
```

### 兼容要求

如果没有 `metadata.fields`，前端继续使用旧的文本输入逻辑。

### 验收标准

针对通信组选择场景，前端应展示：

```text
下一步将定位通信阻塞的 Slow Rank。请选择要分析的通信组。

[ mock_pg / mock_group_hash / 120.5ms / ranks: 0,1 ]
```

而不是只展示：

```text
请补充参数 groupIdHash
```

---

## FR-6：用户提示文案优化

### 描述

系统应生成更符合用户理解的下一步提示。

### 当前不佳提示

```text
下一步 `communication_duration_slow_rank_list` 需要参数：iterationId, groupIdHash。请补充参数。
```

### 期望提示

```text
已完成通信组耗时分析。下一步将定位引发通信阻塞的 Slow Rank。请先选择要继续分析的通信组。
```

### 文案来源

短期内可由后端模板生成。

中期可允许 LLM 在受限上下文中生成，但必须满足：

- 不编造工具；
- 不编造候选项；
- 不隐藏 required 参数；
- 不修改参数值；
- 不影响结构化 `fields/options`；
- LLM 失败时回退到 deterministic 模板。

### 验收标准

用户提示应说明：

- 当前已完成什么；
- 下一步要做什么；
- 用户需要完成什么操作；
- 如果有已继承参数，应避免再次要求用户输入。

---

## FR-7：MCP `NEEDS_USER_INPUT` options 透传

### 描述

如果 MCP 返回 `control_flow.status = NEEDS_USER_INPUT`，并且 `required_inputs` 中包含 `options`，Agent Service 应将这些 options 透传给前端。

### 输入示例

```json
{
  "control_flow": {
    "status": "NEEDS_USER_INPUT",
    "required_inputs": [
      {
        "name": "groupIdHash",
        "description": "请选择通信组",
        "options": [
          {
            "label": "mock_pg",
            "value": "mock_group_hash"
          }
        ]
      }
    ]
  }
}
```

### 输出要求

后端应转换为：

```json
{
  "metadata": {
    "fields": [
      {
        "name": "groupIdHash",
        "description": "请选择通信组",
        "options": [
          {
            "label": "mock_pg",
            "value": "mock_group_hash"
          }
        ]
      }
    ]
  }
}
```

### 验收标准

MCP 返回的 `required_inputs.options` 不应在 Agent Service 转换过程中丢失。

---

## FR-8：LLM 受约束增强

### 描述

系统可增强 LLM 在 Agent 编排中的作用，但必须受 MCP、schema 和 interaction policy 约束。

### LLM 可增强能力

LLM 可以用于：

1. 参数继承解释；
2. 参数字段同义映射建议；
3. 候选项说明；
4. 候选项排序和推荐；
5. 用户提示文案生成；
6. 工具结果摘要；
7. 错误恢复建议；
8. 多轮上下文整理。

### LLM 不允许能力

LLM 不允许：

1. 发明 MCP 未返回的工具；
2. 绕过 MCP `next_step`；
3. 跳过 MCP prerequisite；
4. 构造未出现在候选项中的 `groupIdHash`；
5. 修改 schema required 语义；
6. 在未经确认时执行需要用户选择的分支；
7. 覆盖用户显式输入；
8. 以自然语言结果替代结构化参数校验。

### LLM 输出要求

LLM 输出应为结构化 JSON，例如：

```json
{
  "resolved_params": {
    "iterationId": "3"
  },
  "needs_user_input": [
    {
      "name": "groupIdHash",
      "reason": "存在多个通信组，需要用户选择",
      "options": []
    }
  ],
  "user_prompt": "请选择要分析的通信组。",
  "confidence": 0.9
}
```

### 验收标准

LLM 增强后，所有工具调用仍必须：

- 来自 MCP `next_step`；
- 参数通过 schema/Pydantic 校验；
- 可追踪参数来源；
- LLM 失败时可以 deterministic fallback。

---

## 7. 非功能需求

## NFR-1：可靠性

- LLM 失败不应导致诊断流程不可恢复；
- LLM timeout 后应进入 deterministic fallback；
- 历史参数继承不应依赖 LLM；
- 候选项提取优先使用结构化数据。

---

## NFR-2：可观测性

系统应记录：

- LLM 调用耗时；
- LLM timeout 次数；
- 参数来源；
- missing 参数列表；
- 自动继承的参数；
- 用户选择的参数；
- fallback 发生原因。

---

## NFR-3：可追踪性

每个最终传给 MCP 工具的参数应可追踪来源：

```json
{
  "iterationId": {
    "value": "3",
    "source": "previous_step_args"
  },
  "groupIdHash": {
    "value": "mock_group_hash",
    "source": "user_selected_option"
  }
}
```

---

## NFR-4：兼容性

- 不破坏现有 SSE 事件格式；
- 旧前端在没有 `metadata.fields` 支持时仍能显示基本问题；
- 新前端优先消费 `metadata.fields`；
- MCP 现有 `data.text` 格式暂不强制调整。

---

## NFR-5：安全性与边界

- LLM 不得绕过 MCP 控制流；
- LLM 不得生成不存在的工具名；
- LLM 不得直接执行未确认的用户选择；
- 所有工具参数必须 schema 校验；
- 用户显式输入优先于 LLM 推断。

---

## NFR-6：用户体验

- 用户不应被要求输入系统已经知道的参数；
- 用户应看到可理解的候选项；
- 用户应知道下一步分析的目的；
- 内部字段如 `groupIdHash` 应尽量配合业务描述展示；
- 多个候选项时应支持选择；
- 单个候选项时应自动选择，并可向用户展示“已自动选择唯一候选项”。

---

## 8. 用户故事与验收标准

### US-1：作为诊断用户，我不想重复输入已有参数

**故事**

作为用户，当我已经在前面选择或提供过 `iterationId`，下一步工具仍需要该参数时，系统应自动继承，而不是让我再次输入。

**验收标准**

- Given 前序步骤已有 `iterationId`
- When 下一步 schema required 包含 `iterationId`
- Then 后端自动填充该参数
- And 前端不提示用户补充 `iterationId`

---

### US-2：作为诊断用户，我希望从候选通信组中选择

**故事**

作为用户，当系统发现多个通信组时，我希望看到每个通信组的可读信息，并选择要继续分析的通信组。

**验收标准**

- Given 上一步结果包含多个 `groupIdHash`
- When 下一步需要 `groupIdHash`
- Then 前端展示通信组选项
- And 用户选择后提交对应 `groupIdHash`
- And 后端继续调用下一步 MCP 工具

---

### US-3：作为诊断用户，我希望知道下一步为什么需要我操作

**故事**

作为用户，当系统暂停等待输入时，我希望提示说明当前完成了什么、下一步要做什么、为什么需要我选择。

**验收标准**

- Given 系统进入 `user_input_required`
- Then 提示应包含下一步分析目的
- And 提示不应只是字段名列表
- And 如果存在候选项，应解释候选项含义

---

### US-4：作为开发者，我希望 LLM timeout 日志可诊断

**故事**

作为开发者，当 LLM 参数抽取超时时，我希望日志能显示超时时间、模型、provider、stage、fallback 等信息。

**验收标准**

- Given LLM 调用 timeout
- Then 日志包含 `timeout_seconds`
- And 日志包含 `elapsed_ms`
- And 日志包含 `stage`
- And 日志包含 `provider/model`
- And 日志包含 fallback 行为

---

### US-5：作为开发者，我希望知道每个参数来自哪里

**故事**

作为开发者，当某一步工具被调用时，我希望知道每个参数是用户输入、历史继承、工具输出还是 LLM 抽取出来的。

**验收标准**

- Given 系统准备调用 MCP 工具
- Then 参数 metadata 中包含来源信息
- And 日志或 trace 可查看参数来源
- And LLM 推断参数与 deterministic 参数可区分

---

### US-6：作为系统维护者，我希望增强 LLM 但不破坏 MCP 流程控制

**故事**

作为系统维护者，我希望 LLM 可以帮助理解上下文和生成提示，但不能绕过 MCP `next_step` 和 schema 校验。

**验收标准**

- Given LLM 输出了建议 action
- Then 工具名必须匹配 MCP `next_step.tool_name`
- And 参数必须通过 schema 校验
- And 非法参数被丢弃或触发 fallback
- And MCP prerequisite 仍由 MCP Server 控制

---

## 9. 关键业务流程

### 9.1 修复后的通信组选择流程

```text
用户发起诊断
  ↓
Agent 调用 MCP search_profiler_tools
  ↓
MCP 返回 initial_step
  ↓
Agent 执行 MCP execute_profiler_tool
  ↓
MCP 返回通信组耗时结果和 next_step
  ↓
Agent 从历史上下文继承 iterationId
  ↓
Agent 从上一步结果提取 groupIdHash 候选项
  ↓
Agent 判断真正缺失参数为 groupIdHash
  ↓
Agent 发出 user_input_required，包含 fields/options
  ↓
前端展示通信组选项
  ↓
用户选择 group
  ↓
前端提交 {"groupIdHash": "..."}
  ↓
Agent 合并 inherited iterationId + user selected groupIdHash
  ↓
Agent 校验 schema
  ↓
Agent 调用 communication_duration_slow_rank_list
```

---

### 9.2 LLM timeout fallback 流程

```text
Agent 准备解析下一步参数
  ↓
deterministic context binding
  ↓
调用 LLM 辅助参数抽取
  ↓
LLM timeout
  ↓
记录详细 timeout 日志
  ↓
进入 deterministic fallback
  ↓
使用已继承参数和候选项继续判断
  ↓
如果仍缺用户决策参数，则发起 user_input_required
```

---

### 9.3 受约束 LLM 辅助流程

```text
MCP 返回 next_step/schema
  ↓
Agent 收集 known params/candidates/history
  ↓
LLM 在受限上下文内生成建议
  ↓
Agent 校验 LLM 输出
  ↓
合法部分进入参数解析或提示生成
  ↓
非法部分丢弃
  ↓
工具调用仍通过 MCP execute_profiler_tool
```

---

## 10. 数据需求

### 10.1 参数来源数据

系统应支持记录参数来源：

```json
{
  "name": "iterationId",
  "value": "3",
  "source": "previous_step_args",
  "confidence": 1.0
}
```

来源类型建议包括：

- `user_input`
- `user_selected_option`
- `previous_step_args`
- `previous_step_output`
- `session_context`
- `mcp_context`
- `schema_default`
- `llm_extraction`
- `deterministic_extraction`

---

### 10.2 字段级输入数据

字段结构建议：

```json
{
  "name": "groupIdHash",
  "label": "通信组",
  "type": "select",
  "required": true,
  "description": "Hash identifier of the communication group to analyze.",
  "options": [
    {
      "label": "mock_pg / mock_group_hash / 120.5ms / ranks: 0,1",
      "value": "mock_group_hash",
      "metadata": {
        "pgName": "mock_pg",
        "duration": 120.5,
        "rankList": ["0", "1"]
      }
    }
  ]
}
```

---

### 10.3 LLM 失败日志数据

建议记录：

```json
{
  "stage": "extract_parameters_by_schema",
  "tool_name": "communication_duration_slow_rank_list",
  "required_keys": ["iterationId", "groupIdHash"],
  "timeout_seconds": 30,
  "elapsed_ms": 30012.45,
  "provider": "claude",
  "model": "claude-sonnet-4-6",
  "exception_type": "TimeoutError",
  "exception_repr": "TimeoutError()",
  "fallback": "deterministic_parameter_resolution"
}
```

---

## 11. 约束与原则

### 11.1 MCP 仍是流程权威

所有 profiling 工具执行必须遵守：

```text
search_profiler_tools → initial_step → execute_profiler_tool → next_step
```

Agent 不得绕过 MCP 直接调用内部 profiler tool。

---

### 11.2 LLM 只能在边界内增强

LLM 可以辅助：

- 理解；
- 解释；
- 推荐；
- 生成提示；
- 抽取参数。

但不能决定：

- 非 MCP 返回的工具；
- 非 playbook 允许的跳步；
- 未校验参数；
- 未确认用户选择。

---

### 11.3 结构化数据优先于自然语言

当结构化字段和自然语言文本冲突时，应优先使用结构化字段。

候选项应优先来自结构化数据，而不是 LLM 从 markdown 中猜测。

---

### 11.4 deterministic fallback 必须可用

LLM 失败时，系统仍应能：

- 继承历史参数；
- 判断缺失参数；
- 展示候选项；
- 继续等待用户输入；
- 不崩溃、不误执行。

---

## 12. 已确认产品决策

### D-1：单个候选通信组自动选择

当只有一个 `groupIdHash` 候选项时，系统应自动使用该候选项继续执行，不再要求用户确认。

要求：

- 自动选择的参数来源应记录为 `auto_selected_single_option` 或等价来源；
- 前端可在消息中展示系统已自动选择的通信组；
- 自动选择后仍必须通过 schema/Pydantic 校验；
- 如该步骤未来被标记为高风险或有副作用，应由 interaction policy 另行拦截。

---

### D-2：暂不做 LLM 默认候选推荐

多个通信组候选项场景下，暂不要求 LLM 基于 duration、pgName、rankList 推荐默认分析对象。

要求：

- 多候选时展示候选列表，由用户选择；
- LLM 可以生成普通说明文案，但不生成推荐排序或默认推荐；
- 候选项排序优先保持 MCP/工具返回顺序，或使用确定性规则。

---

### D-3：暂不支持多选字段

当前阶段前端字段级表单暂不需要支持多选。

要求：

- `groupIdHash` 按单选字段处理；
- 字段类型优先支持 `string`、`select`；
- 暂不实现 `multi_select`；
- 如未来出现多 rank、多 operator、多 iteration 对比或多 group 批量分析，再扩展字段模型。

---

### D-4：参数来源可以展示给用户

参数来源信息可以面向用户展示。

示例：

```text
迭代 ID 已沿用上一步：3
```

要求：

- 用户可见文案应使用业务友好的表达；
- 开发调试 metadata 中仍需保留完整参数来源；
- 不应展示过多内部实现细节，但可以说明“已沿用上一步参数”“已自动选择唯一通信组”等。

---

### D-5：LLM 生成用户提示默认开启

允许默认开启 LLM 用户提示生成能力。

建议配置：

```yaml
llm_assistance:
  prompt_composition_enabled: true
```

要求：

- LLM 只生成用户提示文案，不改变结构化参数、候选项和工具调用；
- LLM 失败或超时时回退到 deterministic 模板；
- 生成文案必须基于 MCP `next_step`、schema、候选项和已解析参数，不得编造事实。

---

### D-6：LLM timeout 信息展示给前端

LLM timeout 后，除后端日志外，也应向前端 metadata 暴露简要状态。

示例：

```json
{
  "llm_assistance": {
    "status": "timeout",
    "stage": "extract_parameters_by_schema",
    "fallback": "deterministic_parameter_resolution"
  }
}
```

要求：

- 前端可以展示简短提示，例如“智能参数解析超时，已切换为规则解析”；
- 用户提示应避免过度技术化；
- 后端日志仍需保留完整 timeout 诊断信息；
- LLM timeout 不应阻断 deterministic fallback。

---

## 13. 优先级

### P0

必须优先完成：

1. LLM timeout / exception 日志增强；
2. `iterationId` 历史参数继承；
3. `groupIdHash` 候选项提取；
4. `user_input_required.metadata.fields` 输出；
5. 前端展示字段级 options。

---

### P1

随后完成：

1. MCP `NEEDS_USER_INPUT.required_inputs.options` 透传；
2. 参数来源 metadata，并支持用户可见的参数来源说明；
3. 用户提示文案优化，默认开启受约束 LLM 文案生成并提供 deterministic fallback；
4. 多参数缺失但部分字段有 options 的支持；
5. 单候选自动选择策略；
6. LLM timeout 状态透传给前端。

---

### P2

中长期增强：

1. LLM 受约束提示生成；
2. LLM 候选项推荐；
3. Bounded ReAct 决策结构；
4. 错误恢复建议；
5. 参数同义字段映射。

---

## 14. 成功指标

### 14.1 用户体验指标

- 用户重复输入已有参数的次数下降；
- 缺参提示转化为选择式交互的比例上升；
- 用户无法理解下一步操作的反馈减少；
- 手动输入 `groupIdHash` 等内部字段的次数下降。

---

### 14.2 稳定性指标

- LLM timeout 不影响 deterministic 参数继承；
- 参数校验失败率下降；
- 因缺参导致的流程暂停次数减少；
- 错误提示中未知原因比例下降。

---

### 14.3 可观测性指标

- LLM timeout 日志包含完整上下文；
- 每次工具调用参数来源可追踪；
- 用户输入需求事件包含结构化 fields；
- 候选项提取成功率可统计。

---

## 15. 后续建议

本需求文档完成后，建议下一步进入设计阶段，进一步明确：

1. 后端参数解析链路设计；
2. `AgentRequirement` / SSE event 数据结构；
3. 前端字段级输入组件设计；
4. LLM bounded decision schema；
5. 测试用例设计；
6. 分阶段落地计划。

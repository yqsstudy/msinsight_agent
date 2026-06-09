# 工作流计划：MCP 约束下的智能诊断 Agent 增强

来源设计文档：`docs/mcp_guided_agent_enhancement_design.md`

关联需求文档：`docs/mcp_guided_agent_enhancement_requirements.md`

> 本文档仅作为实施工作流计划，不包含代码实现。后续如需执行，请按阶段使用 `/sc:implement` 或逐项任务推进。

---

## 1. 工作流目标

本工作流用于将“智能诊断 Agent 增强”设计拆解为可执行的实施阶段，覆盖 Backend、Frontend、SSE/API、测试与验收。

目标能力包括：

1. 增强 LLM timeout / exception 日志可观测性；
2. 修复下一步 MCP 工具参数解析时的历史参数继承问题，重点是 `iterationId`；
3. 从上一步 MCP 结果中提取 `groupIdHash` 候选项；
4. 增强 `user_input_required`，支持 `metadata.fields` 字段级输入结构；
5. 支持单候选自动选择、多候选前端选择；
6. 前端渲染字段级输入控件并支持对象形式 continuation；
7. 暴露参数来源与 LLM fallback 状态；
8. 默认开启受约束 LLM 用户提示生成，并提供 deterministic fallback。

---

## 2. 实施边界

### 2.1 本工作流会规划

- Backend 参数解析、候选项提取、用户输入事件增强；
- Frontend 类型、状态、字段级表单渲染与提交；
- LLM 日志与 prompt composer；
- 单元测试、集成测试和验收检查；
- 分阶段实施顺序与依赖关系。

### 2.2 本工作流不规划实现

- 不重构 MCP Server 当前 `data.text` 混合 markdown/JSON 的返回格式；
- 不新增 MCP 顶层工具；
- 不绕过 MCP `search_profiler_tools` / `execute_profiler_tool`；
- 不实现传统自由 ReAct Agent；
- 不让 LLM 自由选择工具、跳过 MCP `next_step` 或修改 schema 语义；
- 不做多选字段；
- 暂不做 LLM 默认候选推荐。

---

## 3. 涉及模块

### 3.1 Backend Agent Service

主要文件：

- `agent-service/src/core/mcp_llm_assistant.py`
- `agent-service/src/core/diagnosis/resolver.py`
- `agent-service/src/core/agents/base.py`
- `agent-service/src/core/agents/diagnosis_agent.py`
- `agent-service/src/models/orchestration.py`
- `agent-service/src/core/orchestrator.py`
- `agent-service/config/config.yaml`

### 3.2 Frontend Agent Web

主要文件：

- `agent-web/src/types/index.ts`
- `agent-web/src/components/ChatView.tsx`
- `agent-web/src/stores/index.ts`
- `agent-web/src/services/api.ts`
- 可选新增：`agent-web/src/components/UserInputPanel.tsx`

### 3.3 测试

建议文件：

- `agent-service/tests/test_mcp_llm_assistance.py`
- `agent-service/tests/test_diagnosis_parameter_resolution.py`
- `agent-service/tests/test_dynamic_mcp_orchestration.py`
- Frontend 组件测试文件，按当前项目测试框架放置。

---

## 4. 总体依赖图

```text
Phase 0 基线确认
  ↓
Phase 1 LLM 日志与 failure metadata
  ↓
Phase 2 参数继承与来源追踪
  ↓
Phase 3 候选项提取与单候选自动选择
  ↓
Phase 4 user_input_required 字段级结构
  ↓
Phase 5 Frontend 字段级交互
  ↓
Phase 6 Prompt Composer
  ↓
Phase 7 端到端验证与回归
```

并行机会：

```text
Phase 1 Backend 日志增强
Phase 5 Frontend 类型预备
可部分并行

Phase 2/3/4 Backend 事件结构完成后
Frontend 字段级交互才能完整联调
```

---

## 5. Phase 0：基线确认与测试保护

### 5.1 目标

在修改前确认现有行为、建立最小回归保护，避免后续改动破坏 MCP 元工具编排。

### 5.2 任务

#### T0.1 确认当前 Backend 关键链路

检查并记录：

- `DiagnosisAgent.run(...)` 如何执行 initial step；
- `DiagnosisAgent.resume(...)` 如何处理用户输入；
- `_execute_tool_and_check_next(...)` 如何处理 MCP result 和 `next_step`；
- `ParameterResolver.resolve_for_step(...)` 当前参数合并顺序；
- `MCPLLMOrchestrationAssistant._chat_json(...)` 当前异常日志行为；
- `AgentRequirement` 到 SSE `user_input_required` 的转换路径。

输出：

- 当前链路说明；
- 后续修改点定位；
- 不改变 MCP meta-tool 调用边界的确认。

#### T0.2 确认当前 Frontend 输入链路

检查并记录：

- `UserInputRequiredData` 类型；
- `ChatView` 对 `user_input_required` 的处理；
- `setPendingInput` 与 `setUserInputRequired` 的关系；
- `handleSubmit` 与 `handleSelectOption` 的 continuation 请求格式。

输出：

- Frontend 兼容策略；
- 是否需要新组件 `UserInputPanel` 的判断。

#### T0.3 建立最小测试基线

建议先运行或确认：

```bash
cd agent-service
pytest tests/test_dynamic_mcp_orchestration.py tests/test_orchestrator_llm_assistance.py -v
```

如 Frontend 已有测试：

```bash
cd agent-web
npm run lint
npm run build
```

### 5.3 完成标准

- 明确所有修改入口；
- 确认现有测试状态；
- 记录任何与设计不一致的现有实现。

---

## 6. Phase 1：LLM 日志增强与 failure metadata

### 6.1 目标

让 LLM timeout / exception 可诊断，并为后续前端展示简化状态提供数据来源。

### 6.2 Backend 任务

#### T1.1 增强 `_chat_json` 日志上下文

文件：`agent-service/src/core/mcp_llm_assistant.py`

修改方向：

- 将 `_chat_json(stage, messages)` 扩展为：

```python
async def _chat_json(
    self,
    stage: str,
    messages: List[Dict[str, str]],
    *,
    log_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    ...
```

- 调用前记录开始时间；
- 异常时计算 `elapsed_ms`；
- timeout 单独捕获 `asyncio.TimeoutError`；
- 普通异常捕获 `Exception`；
- 日志包含：
  - `stage`
  - `exception_type`
  - `exception_repr`
  - `timeout_seconds`
  - `elapsed_ms`
  - `provider`
  - `model`
  - `fallback`
  - `tool_name`
  - `required_keys`
  - `schema_keys`

#### T1.2 增加 LLM 最近失败摘要

短期方案：

- 在 assistant 实例上维护 `_last_failure`；
- 每次调用前清空；
- timeout/error 后写入简化结构：

```json
{
  "status": "timeout",
  "stage": "extract_parameters_by_schema",
  "fallback": "deterministic_parameter_resolution"
}
```

注意：

- 避免跨请求污染；
- 如 assistant 是共享实例，需评估并发风险；
- 如存在明显并发风险，应改为返回包装结果或通过调用栈传递 failure metadata。

#### T1.3 在上层调用传入 log_context

重点 API：

- `extract_parameters_by_schema(...)`
- `extract_parameters(...)`

传入：

- 当前 `tool_name`；
- required keys；
- schema keys；
- fallback 名称；
- 如上下文可得，加入 session/request 相关标识。

### 6.3 测试任务

#### T1.4 Backend 单元测试：timeout 日志

测试点：

- mock LLM 调用 timeout；
- 断言日志不再只有 `TimeoutError:`；
- 断言包含 `timeout_seconds`、`elapsed_ms`、`stage`、`fallback`；
- 断言 `_last_failure` 或返回 metadata 包含简化 timeout 状态。

#### T1.5 Backend 单元测试：普通异常日志

测试点：

- mock provider 抛出异常；
- 断言 `exception_type`、`exception_repr`、`provider/model` 出现在日志或结构化上下文中；
- 断言 deterministic fallback 仍继续。

### 6.4 完成标准

- LLM timeout 日志足够定位问题；
- LLM 失败不会阻断参数解析；
- 后续模块可以读取简化 `llm_assistance` 状态。

---

## 7. Phase 2：参数继承与参数来源追踪

### 7.1 目标

确保 `iterationId` 等历史参数在缺参判断前 deterministic 绑定，不依赖 LLM；同时记录参数来源。

### 7.2 Backend 任务

#### T2.1 扩展 `ParameterResolutionResult`

文件：`agent-service/src/core/diagnosis/resolver.py`

建议新增字段：

```python
param_sources: Dict[str, Any] = Field(default_factory=dict)
llm_assistance: Dict[str, Any] = Field(default_factory=dict)
metadata: Dict[str, Any] = Field(default_factory=dict)
```

如当前模型不是 Pydantic，则按现有 dataclass / class 风格添加默认字段。

#### T2.2 明确参数合并优先级

在 `resolve_for_step(...)` 中实现或校正顺序：

```text
1. MCP suggested_args
2. existing_args
3. current_user_input
4. context known params
5. latest step output params
6. schema defaults
7. LLM advisory extraction
```

关键要求：

- 缺参判断前必须完成 deterministic context binding；
- `iterationId` 来自历史上下文时应填入 arguments；
- 用户本轮显式输入优先于历史参数；
- 冲突走现有 conflict 机制；
- 最终传给工具的参数只保留 schema 允许字段。

#### T2.3 记录参数来源

每次填充参数时同步记录：

```json
{
  "value": "3",
  "source": "previous_step_args",
  "display": "迭代 ID 已沿用上一步：3",
  "confidence": 1.0
}
```

优先覆盖字段：

- `iterationId`
- `groupIdHash`
- 其他当前 required 参数

#### T2.4 接入 LLM failure metadata

当 LLM 抽参失败或 timeout 时，将 Phase 1 的简化失败状态写入 resolution result：

```json
{
  "llm_assistance": {
    "status": "timeout",
    "stage": "extract_parameters_by_schema",
    "fallback": "deterministic_parameter_resolution"
  }
}
```

### 7.3 测试任务

#### T2.5 Backend 单元测试：已有 `iterationId` 不再缺失

场景：

- context 或 previous args 中已有 `iterationId`；
- next_step schema required = `['iterationId', 'groupIdHash']`；
- 没有 `groupIdHash`。

断言：

- `arguments['iterationId']` 存在；
- `missing_required == ['groupIdHash']`；
- `param_sources.iterationId.source` 正确；
- 前端 metadata 不会要求 `iterationId`。

#### T2.6 Backend 单元测试：用户输入覆盖历史参数

场景：

- 历史已有某参数；
- 用户本轮显式输入不同值。

断言：

- 用户输入优先；
- source 为 `user_input`；
- 如现有冲突机制要求确认，则确认分支可正常触发。

### 7.4 完成标准

- `iterationId` 继承稳定；
- missing 参数列表只包含真正缺失字段；
- 参数来源可追踪。

---

## 8. Phase 3：候选项提取与单候选自动选择

### 8.1 目标

从 MCP 结果、schema、known params 等来源提取字段候选项，重点支持 `groupIdHash`；当只有一个候选项时自动选择。

### 8.2 Backend 任务

#### T3.1 新增候选项收集方法

文件：`agent-service/src/core/agents/diagnosis_agent.py`

建议新增：

```python
def _collect_field_options(
    self,
    field_name: str,
    *,
    context: DiagnosisContext,
    metadata: Dict[str, Any],
    schema: Dict[str, Any],
) -> List[Dict[str, Any]]:
    ...
```

或拆分：

- `_extract_group_id_hash_options(...)`
- `_format_group_option(...)`
- `_collect_options_from_known_params(...)`
- `_collect_options_from_schema(...)`
- `_collect_options_from_mcp_required_inputs(...)`

#### T3.2 实现候选项来源优先级

按设计优先级处理：

```text
1. MCP control_flow.required_inputs[*].options
2. next_step schema enum/options
3. candidate_inputs.<field>
4. known_params 中的 <field>_options / <field>Options / candidates
5. known_params 中的 groups / group_candidates
6. latest step output 中包含 field_name 的对象列表
7. text/fenced JSON 中已由现有 produced params 提取出的 data 列表
```

#### T3.3 实现 `groupIdHash` 格式化

对于：

```json
{
  "groupIdHash": "mock_group_hash",
  "pgName": "mock_pg",
  "duration": 120.5,
  "rankList": ["0", "1"]
}
```

生成：

```json
{
  "label": "mock_pg / mock_group_hash / 120.5ms / ranks: 0,1",
  "value": "mock_group_hash",
  "metadata": {...}
}
```

#### T3.4 去重和合法性过滤

要求：

- 过滤空 value；
- 按 value 去重；
- 保持 MCP / 工具返回顺序；
- 不使用 LLM 生成新候选项；
- 候选项值必须可用于当前 schema 字段。

#### T3.5 实现单候选自动选择

在缺参判断后、构建 suspension 前：

- 如果缺失字段存在且候选项只有一个；
- 自动填充该字段；
- source 记录为 `auto_selected_single_option`；
- 重新计算 missing required；
- 如果参数完整，直接继续执行 MCP next_step；
- 如果仍缺其他参数，再构建 user input。

### 8.3 测试任务

#### T3.6 Backend 单元测试：从 MCP output 提取 group options

断言：

- `metadata.fields[0].options` 包含可读 label；
- `value` 是 `groupIdHash`；
- metadata 保留原始字段。

#### T3.7 Backend 单元测试：单候选自动选择

断言：

- 不发 suspension；
- arguments 中含 `groupIdHash`；
- source 为 `auto_selected_single_option`；
- 后续执行仍通过 MCP `execute_profiler_tool`。

#### T3.8 Backend 单元测试：多候选不推荐不自动选

断言：

- 多个候选时进入 `user_input_required`；
- 不设置 recommended/default；
- 保持候选项顺序。

### 8.4 完成标准

- 多个 `groupIdHash` 候选项可传递前端；
- 单候选自动选择；
- 无候选时仍 fallback 到文本输入，不阻断流程。

---

## 9. Phase 4：`user_input_required` 字段级结构

### 9.1 目标

Backend 生成兼容旧前端、支持新前端的字段级输入事件。

### 9.2 Backend 任务

#### T4.1 增强 `_build_suspension_requirement(...)`

文件：`agent-service/src/core/agents/diagnosis_agent.py`

输出结构：

```python
AgentRequirement(
    input_type="params",
    question="...",
    options=[...],
    metadata={
        "tool_name": "communication_duration_slow_rank_list",
        "missing_required": ["groupIdHash"],
        "resolved_arguments": {"iterationId": "3"},
        "param_sources": {...},
        "fields": [...],
        "llm_assistance": {...},
    },
)
```

#### T4.2 构建 `fields`

规则：

- 每个 missing required 都生成一个 field；
- 有 options 时：`type = 'select'`；
- 无 options 时：`type = 'string'`；
- `label` 使用业务友好名称，例如：
  - `groupIdHash` → `通信组`
  - `iterationId` → `迭代 ID`
- `description` 优先来自 schema description 或 MCP required_inputs description。

#### T4.3 顶层 `options` 兼容

规则：

- 当只有一个 missing field 且该 field 是 select 时；
- 将 field options 同步写入 `AgentRequirement.options`；
- 旧前端仍能展示按钮或选项；
- 新前端优先消费 `metadata.fields`。

#### T4.4 MCP `NEEDS_USER_INPUT.required_inputs.options` 透传

在 `_execute_tool_and_check_next(...)` 的 `NEEDS_USER_INPUT` 分支：

- 解析 MCP 返回的 `required_inputs`；
- 将每个 required input 转成 field；
- 保留 options；
- 写入 `metadata.fields`；
- 对单字段 select 同步顶层 options。

#### T4.5 将 resolution metadata 接入 requirement metadata

包括：

- `resolved_arguments`
- `param_sources`
- `llm_assistance`
- `missing_required`
- `tool_name`
- `resume_action`

### 9.3 测试任务

#### T4.6 Backend 单元测试：字段级 requirement

断言：

- `AgentRequirement.input_type == 'params'`；
- `metadata.fields` 存在；
- `metadata.fields[*].name` 与 missing 参数一致；
- select field 有 options；
- 顶层 options 兼容填充。

#### T4.7 Backend 单元测试：MCP required_inputs options 不丢失

断言：

- MCP 返回 options 后，最终 SSE metadata 中仍存在；
- label/value 不被覆盖；
- description 被保留。

### 9.4 完成标准

- `user_input_required` 可以表达字段级参数输入；
- 旧前端兼容；
- 新前端具备足够数据渲染 select/text field。

---

## 10. Phase 5：Frontend 字段级交互

### 10.1 目标

前端优先使用 `metadata.fields` 渲染字段级表单，支持 select/text 输入和对象形式提交。

### 10.2 Frontend 任务

#### T5.1 扩展类型定义

文件：`agent-web/src/types/index.ts`

新增：

```ts
export interface InputFieldOption {
  label: string
  value: string | number | boolean
  description?: string
  metadata?: Record<string, any>
}

export interface InputField {
  name: string
  label?: string
  type?: 'string' | 'select' | 'path' | 'confirm'
  required?: boolean
  description?: string
  value?: any
  options?: InputFieldOption[]
  metadata?: Record<string, any>
}
```

扩展 `UserInputRequiredData.metadata`：

- `fields?: InputField[]`
- `resolved_arguments?: Record<string, any>`
- `param_sources?: Record<string, any>`
- `llm_assistance?: {...}`

#### T5.2 保持 store 兼容

文件：`agent-web/src/stores/index.ts`

最小改动：

- 继续保存完整 `pendingInput`；
- 不强制新增独立 `inputFields`；
- `inputQuestion/inputOptions/inputReason` 保持兼容旧 UI。

#### T5.3 新增或改造 `UserInputPanel`

推荐新增组件：

```text
UserInputPanel
  ├─ FieldInputRenderer
  ├─ SelectField
  ├─ TextField
  └─ SubmitButton
```

也可直接在 `ChatView.tsx` 中实现，但为了降低复杂度，建议拆组件。

渲染优先级：

```text
if pendingInput.metadata.fields exists:
    render field-level form
else if inputOptions exists:
    render legacy option buttons
else:
    render text input
```

#### T5.4 Select 字段交互

对于：

```json
{
  "name": "groupIdHash",
  "label": "通信组",
  "type": "select",
  "options": [{"label": "mock_pg / ...", "value": "mock_group_hash"}]
}
```

实现：

- 展示 label；
- 展示 options label；
- 保存选中 value 到 `formValues[field.name]`；
- required 字段未选择时禁止提交或提示。

#### T5.5 Text 字段交互

对于无 options 字段：

- 渲染文本输入；
- 使用 `label` 和 `description`；
- required 字段为空时禁止提交或提示。

#### T5.6 参数来源和 LLM fallback 展示

当存在：

```json
metadata.param_sources.iterationId.display
```

展示低干扰说明：

```text
已沿用参数：迭代 ID 已沿用上一步：3
```

当存在：

```json
metadata.llm_assistance.status = "timeout"
```

展示：

```text
智能参数解析超时，已切换为规则解析。
```

#### T5.7 对象形式 continuation

字段级表单提交：

```ts
streamApi.continueAnalysis(sessionId, formValues)
```

请求体：

```json
{
  "session_id": "ses_xxx",
  "user_input": {
    "groupIdHash": "mock_group_hash"
  }
}
```

旧逻辑继续支持：

```ts
streamApi.continueAnalysis(sessionId, option.value)
```

### 10.3 测试任务

#### T5.8 Frontend 类型/渲染测试

断言：

- `metadata.fields` 存在时渲染字段级表单；
- select options label 可见；
- text field 可输入；
- 没有 fields 时旧逻辑可用。

#### T5.9 Frontend 提交测试

断言：

- 字段级表单提交对象；
- legacy option 提交 raw value；
- required 字段未填时不提交。

#### T5.10 Frontend 提示展示测试

断言：

- 参数来源 display 可见；
- LLM timeout fallback 提示可见；
- 不展示过多内部技术细节。

### 10.4 完成标准

- 前端能展示通信组候选项；
- 用户选择后提交 `{ groupIdHash: '...' }`；
- 旧事件仍能正常展示和提交。

---

## 11. Phase 6：LLM Prompt Composer

### 11.1 目标

默认开启受约束 LLM 用户提示生成，仅生成 `question` 文案；失败时 deterministic fallback。

### 11.2 Backend 任务

#### T6.1 增加配置项

文件：`agent-service/config/config.yaml`

建议：

```yaml
llm_assistance:
  prompt_composition_enabled: true
  prompt_composition_timeout_seconds: 10
  expose_failure_to_frontend: true
```

如已有 `llm_assistance` 配置，合并而不是覆盖。

#### T6.2 新增 Prompt Composer 方法

可放在：

- `agent-service/src/core/mcp_llm_assistant.py`

或新增轻量类：

- `agent-service/src/core/diagnosis/prompt_composer.py`

输入：

- `tool_name`
- `missing_required`
- `resolved_arguments`
- `param_sources`
- `fields` 简要信息
- 当前诊断状态

输出只接受：

```json
{
  "question": "..."
}
```

#### T6.3 加强输出校验

要求：

- 只读取 `question`；
- 不读取 LLM 输出的参数、工具名、候选项；
- 如果 question 为空或明显异常，fallback；
- 如果超时，fallback；
- 如果 LLM 文案与结构化字段冲突，fallback。

#### T6.4 接入 `_build_suspension_requirement(...)`

在构造 fields/options 后：

1. 生成 deterministic question；
2. 如果配置开启，调用 prompt composer；
3. 成功则使用 LLM question；
4. 失败则使用 deterministic question；
5. metadata 中记录 `llm_assistance` 状态。

### 11.3 测试任务

#### T6.5 Backend 单元测试：Prompt Composer 成功

断言：

- question 使用 LLM 返回；
- fields/options 不受影响；
- tool_name/arguments 不被 LLM 修改。

#### T6.6 Backend 单元测试：Prompt Composer timeout fallback

断言：

- question 使用 deterministic fallback；
- metadata.llm_assistance.status 为 timeout；
- 流程继续。

#### T6.7 Backend 单元测试：非法 LLM 输出 fallback

断言：

- LLM 输出包含非 question 字段不会被采纳；
- LLM 输出空 question 时 fallback。

### 11.4 完成标准

- 用户提示更自然；
- LLM 失败不影响结构化输入；
- LLM 不能改变工具调用和参数。

---

## 12. Phase 7：端到端验证与回归

### 12.1 目标

验证完整诊断链路满足设计验收标准，并确保原有 MCP 动态编排不被破坏。

### 12.2 Backend 验证

建议运行：

```bash
cd agent-service
pytest tests/test_mcp_llm_assistance.py -v
pytest tests/test_diagnosis_parameter_resolution.py -v
pytest tests/test_dynamic_mcp_orchestration.py -v
pytest tests/test_orchestrator_llm_assistance.py -v
```

如果时间允许：

```bash
cd agent-service
pytest tests/ -v
```

### 12.3 Frontend 验证

建议运行：

```bash
cd agent-web
npm run lint
npm run build
```

如有组件测试：

```bash
cd agent-web
npm test
```

### 12.4 手工联调场景

#### 场景 A：已有 iterationId + 多个 groupIdHash

输入：

- 前序 MCP result 中包含 `iterationId`；
- 上一步 output 中包含多个 group；
- next_step required 包含 `iterationId`、`groupIdHash`。

期望：

- 后端 missing 只有 `groupIdHash`；
- SSE `metadata.fields` 有 select field；
- 前端展示多个通信组选项；
- 用户选择后提交对象；
- 后端合并 inherited `iterationId` 和 user selected `groupIdHash`；
- 继续调用 MCP `execute_profiler_tool`。

#### 场景 B：已有 iterationId + 单个 groupIdHash

期望：

- 后端自动选择唯一 group；
- 不发 `user_input_required`；
- 参数来源记录 `auto_selected_single_option`；
- 继续执行 next_step。

#### 场景 C：LLM timeout

期望：

- 日志包含 timeout 详细信息；
- 前端 metadata 可收到简化 timeout 状态；
- deterministic fallback 继续；
- 不重复要求用户输入 `iterationId`。

#### 场景 D：MCP NEEDS_USER_INPUT options

期望：

- MCP required_inputs options 被转换为 `metadata.fields[*].options`；
- 前端可展示并提交；
- options 不丢失。

#### 场景 E：无 metadata.fields 的旧事件

期望：

- 前端仍使用 legacy `question + options` 或文本输入；
- 无回归。

### 12.5 完成标准

满足设计文档 14 节全部验收标准：

1. LLM timeout 日志可定位 stage、timeout、provider/model、fallback；
2. 已存在 `iterationId` 时不会再次要求用户输入；
3. 多个 `groupIdHash` 候选项时前端展示选择控件；
4. 单个 `groupIdHash` 候选项时后端自动选择并继续执行；
5. `user_input_required` 包含 `metadata.fields`；
6. 前端能提交对象形式参数；
7. 参数来源可展示给用户，也可在 metadata 中追踪；
8. LLM timeout 状态可在前端以简短提示展示；
9. LLM 用户提示生成默认开启，但失败时不影响流程；
10. 所有工具调用仍遵守 MCP `next_step` 和 schema 校验。

---

## 13. 推荐任务执行顺序

### 13.1 最小可交付路径

如果希望尽快修复用户当前遇到的问题，按以下顺序实施：

```text
1. T1.1 - T1.4：LLM timeout 日志增强
2. T2.1 - T2.5：iterationId 历史继承
3. T3.1 - T3.4：groupIdHash 候选项提取
4. T4.1 - T4.3：metadata.fields 输出
5. T5.1 - T5.7：前端字段级展示和对象提交
6. T3.5：单候选自动选择
7. T7 手工联调
```

### 13.2 完整设计路径

如果希望一次性完成设计文档全部能力：

```text
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
```

### 13.3 可并行任务

可并行：

- Backend LLM 日志增强 与 Frontend 类型定义预备；
- Backend 参数来源模型 与 Frontend 参数来源展示 UI；
- Prompt Composer 配置 与 Frontend LLM fallback 提示展示。

不可并行或需等待：

- Frontend 字段级完整联调需等待 Backend `metadata.fields` payload；
- 单候选自动选择需等待候选项提取；
- Prompt Composer 接入需等待 fields/resolved arguments/param_sources 已形成。

---

## 14. 风险控制点

### 14.1 并发状态污染

如果使用 assistant 实例级 `_last_failure`，需确认 assistant 是否 per request / per session。

规避：

- 每次调用前清空；
- 尽量在调用栈中传递 failure metadata；
- 测试并发场景或避免全局共享状态。

### 14.2 自动选择误选

规避：

- 只在候选项唯一时自动选择；
- 记录来源；
- 保留 interaction policy 高风险拦截；
- 不对多候选做推荐或默认选择。

### 14.3 LLM 文案不一致

规避：

- 只采纳 `question`；
- 不采纳任何参数和候选项；
- 对空文案、异常文案 fallback；
- 结构化 fields/options 永远优先。

### 14.4 旧前端兼容

规避：

- 保留顶层 `options`；
- `metadata.fields` 为新增字段；
- `/api/stream/continue` 继续接受 string。

---

## 15. 最终交付物清单

### 15.1 Backend

- LLM timeout / exception 详细日志；
- LLM failure 简要 metadata；
- 参数来源追踪；
- `iterationId` 历史继承修复；
- `groupIdHash` 候选项提取；
- 单候选自动选择；
- `user_input_required.metadata.fields`；
- MCP `NEEDS_USER_INPUT.required_inputs.options` 透传；
- Prompt Composer 与 fallback。

### 15.2 Frontend

- `InputField` / `InputFieldOption` 类型；
- 字段级输入渲染；
- select/text field 支持；
- 参数来源展示；
- LLM timeout fallback 展示；
- 对象形式 continuation；
- legacy 输入兼容。

### 15.3 Tests

- LLM timeout 日志测试；
- 参数继承测试；
- 候选项提取测试；
- 单候选自动选择测试；
- 多候选 user_input_required 测试；
- MCP NEEDS_USER_INPUT options 透传测试；
- Prompt Composer fallback 测试；
- Frontend 字段级渲染和提交测试；
- E2E 手工联调记录。

---

## 16. 下一步建议

建议后续使用 `/sc:implement` 或显式实施请求，从 **Phase 1 + Phase 2 + Phase 3 的最小可交付路径** 开始：

1. 先修复 LLM timeout 日志；
2. 再修复 `iterationId` 历史继承；
3. 再实现 `groupIdHash` 候选项提取和 `metadata.fields`；
4. 最后接前端字段级表单。

这样可以最快解决当前线上暴露的两个核心问题，同时保持 MCP 元工具架构边界不变。

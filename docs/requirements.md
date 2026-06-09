# MSInsight Agent Harness 需求规格文档

## 1. 项目背景

当前存在三个相关工程：

| 工程 | 路径 | 现状定位 |
| --- | --- | --- |
| Agent Harness | `D:\Project\msinsight_agent` | 当前目录，已有 FastAPI 后端、React 前端、SSE 流式交互、DAG 工作流、MCP transport、会话与报告相关模块 |
| MSInsight MCP | `D:\Project\新建文件夹\mcp` | 面向 C++ profiling 后端的 MCP Gateway，已实现 playbook、状态机、Context Board、Step Navigator、参数校验和 MCP 多 transport |
| MS-RAG | `D:\Project\ms_rag` | 面向昇腾性能定位知识的 RAG 系统，已实现 FastAPI、混合检索、重排序、知识图谱增强、多级缓存、SSE 问答和 Vue 前端 |

原 Agent 工程曾承担 MCP 流程编排职责，但 MCP 工程现在已经内建专家 Playbook、DAG 分支、强制依赖检查、参数补全和下一步导航。因此，Agent 工程不应继续重复 MCP 分析流程编排，而应升级为上层 **Agent Harness / Task Orchestrator**。

## 2. 总体目标

构建一个工业级性能诊断 Agent Harness，将 MS-RAG 的知识能力与 MSInsight MCP 的 profiling 工具执行能力统一编排起来，为用户提供自然语言驱动的性能诊断、证据融合和可审计报告生成能力。

目标不是把 RAG 与 MCP 简单拼接，而是形成清晰分层：

```text
用户 / 前端
   ↓
Agent Harness
   ├── 意图识别
   ├── 会话管理
   ├── 任务调度
   ├── RAG 调用
   ├── MCP 调用
   ├── 证据融合
   ├── 多轮交互
   └── 报告生成
   ↓                  ↓
MS-RAG              MSInsight MCP
知识依据             profiling 工具执行与 playbook 流程控制
```

## 3. 产品定位

### 3.1 Agent Harness 定位

Agent Harness 是用户任务层和交互层，负责：

- 理解用户意图
- 管理诊断会话
- 判断是否需要查知识库
- 判断是否需要调用 profiling 工具
- 管理用户输入缺口
- 汇总 RAG 与 MCP 证据
- 生成最终诊断结论与报告
- 对外提供统一 API 与流式交互体验

### 3.2 MSInsight MCP 定位

MSInsight MCP 是 profiling 工具专家服务，负责：

- 通过 MCP 暴露 `search_profiler_tools` 和 `execute_profiler_tool`
- 管理性能分析 playbook
- 维护工具执行顺序、前置依赖和跳步拦截
- 执行内部原子工具
- 连接底层 C++ profiling 后端
- 返回工具 observation、下一步 schema 和执行进度

Agent Harness 不应绕过 MCP 直接调用 MCP 内部工具，也不应复制 MCP playbook 状态。

### 3.3 MS-RAG 定位

MS-RAG 是性能定位知识专家服务，负责：

- 提供文档检索
- 提供知识问答
- 返回来源引用
- 返回相关主题
- 提供定位流程、工具使用、概念解释和历史经验依据

Agent Harness 应优先通过 MS-RAG HTTP API 使用其能力，而不是直接 import RAG 内部模块。

## 4. 用户目标

目标用户包括：

- AI 训练 / 推理性能分析人员
- 昇腾平台开发者
- 算法工程师
- 性能优化工程师
- 需要使用 MindStudio、msprof、profiling 数据进行问题定位的用户

用户期望：

1. 不需要理解底层 MCP 工具调用细节，也能完成性能诊断。
2. 不需要在文档中搜索定位流程，Agent 能主动引用知识库依据。
3. 能基于真实 profiling 数据得到诊断结论，而不是纯文档问答。
4. 能看到诊断结论背后的证据来源。
5. 能在工具需要选择参数时获得清晰解释和建议。
6. 能保存、恢复和回看历史诊断会话。

## 5. 核心原则

### 5.1 分层清晰

- RAG 管知识。
- MCP 管工具与 profiling playbook。
- Agent Harness 管用户任务、调度和证据融合。

### 5.2 不重复编排

Agent Harness 不再维护 MCP 具体分析步骤 DAG，例如：

```text
import_trace_file → communication_duration_iterations → get_units_in_range
```

这些流程应由 MCP playbook 和 Step Navigator 负责。

### 5.3 证据优先

Agent 输出结论必须尽可能基于明确证据：

- RAG 文档片段与来源
- MCP 工具 observation
- 用户输入
- 会话上下文

### 5.4 工业可审计

每次诊断应能追踪：

- 用户提出了什么问题
- 调用了哪些 RAG / MCP 能力
- 每次调用输入输出是什么
- 结论依据是什么
- 哪些地方存在不确定性

### 5.5 分层多 Agent 协作

项目采用主从分层协作模式：

```text
Orchestrator (Parent Agent) + Specialized Worker Agents (Retrieval, Diagnosis)
```

- **分层控制**：Orchestrator 管理全局状态，Worker 专注领域任务。
- **信号机制**：Worker 遇到阻塞时发出 Suspend 信号，由 Orchestrator 中转请求用户输入。
- **黑板模式**：通过数据库共享 Evidence，避免 Agent 间直接传递长文本历史。

## 6. 功能需求

### 6.1 意图识别与任务路由

Agent Harness 应识别用户输入类型，并选择合适路径。

| 意图类型 | 示例 | 处理方式 | 优先级 |
| --- | --- | --- | --- |
| 普通聊天 | “你好”、“你能做什么？” | Chat 回答，不调用 RAG/MCP | P0 |
| 知识问答 | “msprof 怎么分析通信耗时？” | 调用 MS-RAG `/qa` 或 `/retrieve`，生成带来源回答 | P0 |
| 文档检索 | “找一下快慢卡定位相关资料” | 调用 MS-RAG `/retrieve` | P0 |
| 性能诊断 | “训练通信很慢，帮我分析” | MCP 优先执行 profiling 分析，必要时 RAG 后置增强 | P0 |
| profiling 文件分析 | “帮我分析这个 json 文件” | MCP 为主，RAG 用于解释、建议和报告引用 | P0 |
| 工具操作咨询 | “这个工具参数是什么意思？” | RAG 问答，必要时结合 MCP schema | P1 |
| 报告生成 | “把这次分析总结成报告” | 基于 evidence store 生成报告 | P0 |
| 会话继续 | “继续刚才的分析” | 恢复 session state，继续 MCP 下一步 | P1 |

### 6.2 RAG 集成

Agent Harness 应提供 RAG Client，调用 MS-RAG HTTP API。

必需能力：

- 调用 `/api/v1/qa` 完成纯知识问答。
- 调用 `/api/v1/retrieve` 获取诊断所需文档证据。
- 可选调用 `/api/v1/qa/stream` 支持流式知识回答。
- 保留 RAG 返回的 sources、keywords、question_type、related_topics、cached 信息。

使用策略：

| 场景 | 推荐 API |
| --- | --- |
| 用户只问概念、流程、工具用法 | `/qa` 或 `/retrieve` |
| Agent 需要解释 MCP 结果、补充建议或生成报告引用 | `/retrieve` |
| MCP 不可用且用户同意降级为知识建议 | `/retrieve` 或 `/qa` |
| 前端要求知识回答流式展示 | `/qa/stream` |

### 6.3 MCP 集成

Agent Harness 应提供 MCP Client，调用 MSInsight MCP 的两个 meta tools。

必需能力：

- 连接 MCP stdio / SSE / WebSocket transport，具体 transport 通过配置控制。
- 调用 `search_profiler_tools(query, select_playbook?)`。
- 调用 `execute_profiler_tool(tool_name, arguments)`。
- 保存 MCP 返回的文本、结构化信息、下一步提示和错误信息。
- 当 MCP 返回缺少 profiling 文件路径、参数无效、前置步骤缺失等提示时，转化为用户可理解的交互问题。

约束：

- 不直接调用 MCP 内部 `tools/**`。
- 不在 Agent Harness 中硬编码 MCP playbook 步骤链。
- 不复制 MCP 的 execution history、Context Board 或 Step Navigator 状态。

### 6.4 诊断 Orchestrator

Agent Harness 应实现主调度器，支持以下诊断流程：

```text
用户问题
  ↓
识别意图并生成执行计划
  ↓
普通聊天：直接生成回答，不调用 RAG/MCP
知识咨询：调用 RAG，生成带来源的知识回答
分析诊断：优先调用 MCP search_profiler_tools / execute_profiler_tool
  ↓
保存 MCP observation，并根据 MCP 下一步提示继续执行或请求用户输入
  ↓
必要时调用 RAG retrieve 对 MCP 结果进行解释、建议和报告引用增强
  ↓
融合 user_input、mcp_observation、rag_evidence 与 agent_conclusion
  ↓
生成诊断结论 / 报告
```

Orchestrator 应支持：

- 显式执行计划：每轮请求应形成可记录、可展示、可恢复的 ExecutionPlan。
- 普通聊天路径：不调用 RAG/MCP，不生成诊断报告。
- 知识咨询路径：仅调用 RAG，返回带来源的知识回答。
- 分析诊断路径：MCP 优先，RAG 仅在需要解释、建议、报告引用或降级知识建议时后置调用。
- 自动路径：参数充分时连续执行若干只读步骤。
- 人工确认路径：涉及用户选择、路径输入、耗时操作或潜在副作用时暂停询问。
- 失败恢复：MCP 或 RAG 调用失败时保留已获得证据，并说明当前阻塞点。

### 6.5 多轮交互

Agent Harness 应在以下场景主动发起多轮交互：

- 缺少 profiling 文件路径。
- MCP 返回需要用户选择候选项。
- 工具参数不完整或校验失败。
- RAG 证据不足，需用户补充问题背景。
- 存在多个 playbook 候选，需要用户确认。
- 继续执行可能耗时较长或涉及有副作用操作。

交互输出应包含：

- 当前需要用户提供什么。
- 为什么需要该信息。
- 可选项是什么。
- 推荐选项及理由。

### 6.6 Evidence Store

Agent Harness 应维护统一证据模型，用于保存和追踪 RAG、MCP 与用户输入。

证据类型至少包括：

| 类型 | 来源 | 内容 |
| --- | --- | --- |
| `rag_evidence` | MS-RAG `/retrieve` 或 `/qa` | 文档片段、来源、相关主题、置信信息 |
| `mcp_observation` | MSInsight MCP | 工具名、参数、返回内容、playbook 信息、下一步提示 |
| `user_input` | 用户 | 文件路径、选择项、问题补充 |
| `agent_conclusion` | Agent Harness | 中间判断、最终结论、置信度、不确定性 |

每条 evidence 应至少包含：

- `id`
- `type`
- `source`
- `content`
- `metadata`
- `created_at`

### 6.7 报告生成

Agent Harness 应基于 Evidence Store 生成诊断报告。

报告内容应包含：

1. 问题摘要
2. 当前结论
3. 证据链
4. MCP 实测结果
5. RAG 知识依据
6. 可能根因排序
7. 建议下一步操作
8. 风险与不确定性
9. 引用来源

报告应区分：

- 已确认事实
- 基于证据的推断
- 仍需用户或工具进一步确认的问题

### 6.8 会话管理

Agent Harness 应支持会话级状态管理。

会话状态至少包含：

- `session_id`
- `user_goal`
- `current_intent`
- `current_stage`
- `active_playbook_id`，如 MCP 返回或用户选择
- `pending_user_input`
- `evidence_ids`
- `created_at`
- `updated_at`

会话管理要求：

- 支持创建新会话。
- 支持恢复历史会话。
- 支持查看会话中的证据和报告。
- 支持在 MCP 等待下一步参数时恢复执行。

### 6.9 流式输出

Agent Harness 应继续支持前端 SSE 流式体验。

流式事件建议包括：

| 事件 | 含义 |
| --- | --- |
| `message_start` | 开始响应 |
| `message_delta` | LLM 文本增量 |
| `rag_retrieval` | RAG 检索完成 |
| `mcp_tool_start` | MCP 工具开始执行 |
| `mcp_tool_result` | MCP 工具返回结果 |
| `user_input_required` | 需要用户输入 |
| `analysis_result` | 诊断阶段性结论 |
| `report_ready` | 报告生成完成 |
| `error` | 错误事件 |
| `message_end` | 响应结束 |

### 6.10 配置管理

Agent Harness 应通过配置管理外部服务地址和行为策略。

配置项包括：

- MS-RAG API base URL
- MSInsight MCP transport 类型
- MCP SSE / WebSocket URL 或 stdio command
- LLM provider、model、API key、base URL
- 是否允许自动连续执行 MCP 步骤
- 自动执行最大步数
- 工具调用超时时间
- RAG top_k
- 日志级别

## 7. 非功能需求

### 7.1 可维护性

- RAG、MCP、LLM 调用必须通过 adapter/client 封装。
- Orchestrator 不应直接依赖第三方服务内部实现。
- 新增 RAG 服务或 MCP transport 不应影响核心诊断逻辑。

### 7.2 可观测性

系统应记录：

- request id / session id
- 用户问题
- 意图识别结果
- RAG 调用耗时与结果数量
- MCP 工具名、参数和耗时
- LLM 调用耗时
- 错误堆栈
- 最终报告生成耗时

### 7.3 安全性

- 用户提供的文件路径不得由 Agent Harness 自行放宽 MCP 的路径安全策略。
- 涉及执行、写入、修改配置、长时间任务的操作应请求用户确认。
- API key 不得写入日志或报告。
- 报告中应避免泄露本地敏感路径之外的无关系统信息。

### 7.4 可靠性

- RAG 服务不可用时，Agent 应能降级为仅 MCP 实测分析，并明确说明缺少知识依据。
- MCP 服务不可用时，Agent 应能降级为 RAG 知识问答，并明确说明无法基于真实 profiling 数据验证。
- 单次工具失败不应导致整个会话丢失。
- 已收集 evidence 应持久化或可恢复。

### 7.5 性能

初始目标：

| 操作 | 目标 |
| --- | --- |
| 意图识别 | < 2s |
| RAG retrieve | < 5s |
| RAG qa 首 token | < 8s |
| MCP 单工具调用 | 取决于底层 C++ 后端，Agent 应展示进度 |
| 报告生成 | < 15s |

### 7.6 可测试性

应支持：

- Mock RAG Client 测试路由逻辑。
- Mock MCP Client 测试多轮诊断状态机。
- 使用真实 RAG API 做集成测试。
- 使用 MCP 测试 server 或固定响应做集成测试。
- 对报告结构做 snapshot 或 schema 测试。

## 8. 用户故事与验收标准

### 8.1 普通聊天

**用户故事**：作为用户，我想进行普通对话或询问 Agent 能力，以便了解系统能做什么。

验收标准：

- 用户提出问候、能力介绍、非知识库/非诊断类问题时，Agent 不调用 MS-RAG。
- 用户提出普通聊天时，Agent 不调用 MSInsight MCP。
- 返回内容应明确系统能力边界，不声称已执行性能分析。

### 8.2 知识问答

**用户故事**：作为性能分析用户，我想直接询问 msprof 或 MindStudio 的使用方法，以便快速获得带来源的说明。

验收标准：

- 用户提出知识类问题时，Agent 调用 MS-RAG。
- 返回答案包含来源引用或相关主题。
- 不调用 MCP profiling 工具。

### 8.3 profiling 文件诊断

**用户故事**：作为性能分析用户，我想提供 profiling 文件路径，让 Agent 自动选择合适的 MCP playbook 并分析性能问题。

验收标准：

- Agent 能识别这是诊断任务。
- Agent 生成执行计划，计划中应体现 MCP 优先。
- Agent 优先调用 MCP `search_profiler_tools`。
- Agent 在需要文件路径时向用户询问。
- Agent 调用 MCP `execute_profiler_tool`。
- Agent 保存 MCP observation。
- Agent 仅在需要解释 MCP 结果、补充建议、生成报告引用或用户要求时调用 RAG。
- Agent 最终输出包含实测证据的诊断结论。

### 8.4 多候选 playbook 选择

**用户故事**：作为用户，当 MCP 返回多个分析剧本时，我希望 Agent 解释每个选项并给出推荐。

验收标准：

- Agent 展示候选 playbook。
- Agent 解释每个候选适用场景。
- Agent 不擅自选择高风险或明显不确定的路径。
- 用户选择后 Agent 使用 `select_playbook` 继续。

### 8.5 参数缺失处理

**用户故事**：作为用户，当工具缺少参数时，我希望 Agent 告诉我缺少什么以及为什么需要。

验收标准：

- Agent 能从 MCP 错误或 next step schema 中识别缺失参数。
- Agent 发出 `user_input_required` 事件。
- 用户补充后能继续当前会话。

### 8.6 诊断报告生成

**用户故事**：作为用户，我希望将一次诊断过程沉淀为报告，方便复盘和分享。

验收标准：

- 报告包含问题摘要、结论、证据链、实测结果、知识依据、建议和不确定性。
- 报告能区分 MCP 实测证据和 RAG 文档依据。
- 报告引用会话中保存的 evidence。

## 9. 约束与边界

### 9.1 不在当前阶段范围内

- 不重写 MS-RAG 内部检索架构。
- 不重写 MSInsight MCP playbook / Context Board / Step Navigator。
- 不实现自由对话式多 Agent 协作。
- 不绕过 MCP 调用 C++ profiling 后端。
- 不在 Agent Harness 中维护 MCP 具体步骤 DAG。
- 不实现复杂企业多租户权限系统。

### 9.2 当前阶段保留能力

当前 Agent 工程已有能力中建议保留：

- FastAPI 后端
- React 前端
- SSE 流式输出
- 会话 API
- MCP transport 基础能力
- error handling
- observability
- report generator 的基础结构

当前 Agent 工程已有能力中建议弱化或重构：

- `core/dag` 作为 MCP 主流程编排器的职责
- `config/flows.yaml` 中对 MCP 分析流程的硬编码配置
- 与 MCP playbook 重叠的工具依赖控制逻辑

## 10. 多 Agent 演进要求

第一阶段不要求实现多 Agent。

后续满足以下条件时，可演进到结构化 worker 模式：

- 单次诊断需要并行分析多个维度，如通信、算子、数据加载、系统资源。
- MCP 工具调用存在长任务，需要异步任务管理。
- 报告生成需要独立质量审查。
- 需要不同专家视角交叉验证根因。

推荐后续形态：

```text
Coordinator
  ├── RetrievalWorker
  ├── MCPExecutionWorker
  ├── DiagnosisWorker
  └── ReportWorker
```

要求：

- Worker 必须结构化输入输出。
- Coordinator 统一决策。
- 不采用无约束的 Agent 间自由聊天作为核心链路。

## 11. 已确认决策

1. **部署方式采用可配置模式**：Agent Harness 应支持配置化连接外部 MS-RAG 与 MCP 服务；第一阶段不强制三者统一进程部署，后续可扩展为由 Harness 或启动器统一拉起依赖服务。
2. **普通聊天使用固定产品说明**：普通聊天、问候和能力介绍不调用 RAG/MCP，也不默认调用 LLM；返回固定能力边界说明，避免把闲聊误判为知识检索或 profiling 诊断。
3. **意图识别采用规则优先 + 可选 LLM 结构化兜底**：第一阶段规则路由优先；推荐高置信阈值 `0.85`，低置信阈值 `0.60`。`>=0.85` 直接执行，`0.60~0.85` 可进入 LLM 结构化分类或上下文补判，`<0.60` 请求用户澄清。
4. **MCP transport 第一阶段优先使用 stdio**：stdio 适合本地集成和初期调试；后续应保留 SSE / WebSocket 配置能力，用于服务化、远程调试或 Studio 类调试入口。
5. **MCP tools 加载采用后台预检 + 请求时连接**：启动时可做后台健康检查和 meta tools 预检，但不阻塞服务启动；实际 MCP 连接仍在分析请求需要时建立，错误通过 SSE 明确暴露给前端。
6. **自动执行边界由 MCP 返回驱动**：Agent 不应每一步都询问用户，而是根据 MCP 返回内容判断是否继续自动执行；仅在需要用户选择、补充参数、选择执行路径、确认潜在副作用或处理不确定分支时进入多轮交互。默认 `max_auto_steps=5`，表示在无需用户补充参数、无需路径选择且无副作用风险的情况下，一次用户请求中最多连续自动推进 5 个 MCP playbook 步骤；该限制不包含 RAG retrieve、playbook search 和失败重试。
7. **ExecutionPlan 独立持久化**：执行计划需要独立落库，并记录每个 step 的状态、输入、输出、耗时、失败原因和关联 evidence，用于历史回看、失败恢复、审计和前端 Timeline 展示。
8. **Evidence Store 第一阶段沿用 session.db**：当前会话数据库 `sessions.db` 本质上可作为 SQLite 存储基础，第一阶段优先复用或扩展现有 session 存储，而不是新增独立数据库。
9. **诊断链路中 MCP 优先、RAG 后置增强**：分析类请求应优先调用 MSInsight MCP 基于真实 profiling 数据执行诊断；RAG 在 MCP 之后用于解释结果、补充建议、生成报告引用，或在 MCP 不可用且用户同意时提供降级知识建议。后续如引入多 Agent，可重新评估是否让 RAG 侧生成独立专家意见。
10. **分析类 RAG 按条件后置调用**：触发条件包括用户要求解释/依据/建议/报告、MCP 结果需要知识解释、MCP 置信不足、发现问题需要补充优化建议、生成报告引用，或 MCP 不可用后的降级知识建议。
11. **MCP 不可用时先询问再降级**：分析类请求中 MCP 不可用时，不直接把 RAG 建议伪装为实测结论；应询问用户是否降级为 RAG 知识建议，并在结果中明确“未经过真实 profiling 数据验证”。
12. **路径校验第一阶段只做格式校验**：Agent Harness 不做本地路径存在性强校验，因为 MCP 可能运行在不同机器或容器中；路径可访问性由 MCP 和底层 profiling 后端判断。
13. **副作用策略**：默认允许自动执行只读分析类 MCP 工具；涉及写入、覆盖、删除文件，修改配置或外部系统状态，启动/停止/提交任务，长时间占用显著资源，目标或参数存在歧义，或 MCP 返回需要用户选择执行路径/参数时，必须请求用户确认。
14. **知识问答默认不生成报告**：纯知识问答默认只返回答案和来源；只有用户明确要求“整理成报告/方案/总结”时，才可进入报告生成并保存到 reports 表。
15. **报告是持久化 Markdown 诊断产物**：报告不同于普通最终回答。普通回答是本轮对话输出；报告是基于 Evidence Store 生成、可回看、可审计的 Markdown 文档，需区分 MCP 实测证据、RAG 知识依据、推断和不确定性。
16. **报告触发采用条件策略**：分析类请求不默认每次都生成报告；仅在用户明确要求、MCP 完成且需要复盘、发现明显问题需要沉淀，或进入报告生成意图时生成。
17. **报告输出格式**：第一阶段以前端展示为主，并将 Markdown 报告文本保存到 `session.db`；暂不实现 PDF 导出。
18. **案例与反馈闭环**：第一阶段只记录用户反馈和采纳情况，不自动写回 RAG corpus；后续如需进入知识库，应增加人工审核流程。
19. **前端统一策略**：Agent React 前端作为统一用户入口；MS-RAG Vue 前端保留为知识库调试/管理入口。
20. **前端展示完整过程**：前端应展示 ExecutionPlan、每个 step 状态、RAG/MCP evidence 引用、pending input 和降级原因，用于支撑用户理解、历史回看和故障排查。
21. **服务启动方式**：第一阶段 RAG 手动启动；MCP 使用 stdio 时通常由 Agent 后端按需拉起。Agent Harness 只根据配置连接外部服务，便于调试和问题定位。

## 12. 阶段性交付建议

### Phase 1：边界重构

- 明确 Agent Harness 不再负责 MCP 具体步骤 DAG。
- 新增 RAG Client。
- 新增 MCP Client。
- 建立基础 Intent Router。

### Phase 2：诊断主链路

- 实现知识问答路径。
- 实现 RAG retrieve + MCP search + MCP execute 的诊断路径。
- 实现 `user_input_required` 多轮交互。

### Phase 3：证据与报告

- 实现 Evidence Store。
- 重构 Report Generator 基于 evidence 输出。
- 支持会话恢复和报告回看。

### Phase 4：工业化增强

- 完善可观测性。
- 完善错误降级。
- 增加集成测试。
- 引入结构化 worker，但不做自由多 Agent。

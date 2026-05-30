# MSInsight Agent 架构演进与多 Agent 协作设计指南

## 一、 当前项目架构评估

当前项目 (`msinsight_agent`) 展示了扎实的工程实现和超前的架构设计，在核心引擎、工程化韧性、可观测性维度上已经接近工业级水平。

### 1.1 架构亮点
* **动态编排机制**：通过 `Orchestrator` 与 `ExecutionPlanner` 实现了基于用户意图（Intent）动态生成执行计划，摒弃了死板的静态配置，具备极强的灵活性。
* **MCP 与 RAG 深度整合**：完美融合了工具执行（实测数据）与知识库检索（经验指导）。
* **工程韧性与可观测性**：内置熔断器（`CircuitBreaker`）、统一异常处理、Prometheus 监控指标与流式（SSE）状态输出。
* **统一证据中心**：首创性地使用 `Evidence` 模型，将每一次 MCP 工具观测和 RAG 检索固化为结构化数据，为后续审计和生成报告提供了坚实基础。

### 1.2 生产环境改进建议 (瓶颈与风险)
* **持久化瓶颈**：当前基于 `sqlite3` 的 `SessionStore` 在多用户高并发场景下存在写锁瓶颈，需向 PostgreSQL 迁移。
* **安全机制缺失**：API 路由缺乏鉴权（JWT/API Key），敏感配置强依赖本地文件。
* **环境与部署**：需推进容器化（Docker/Docker-Compose）以消除硬编码路径和环境耦合。

---

## 二、 架构演进方向：分层多 Agent (Orchestrator-Worker)

尽管项目已具备动态编排能力，随着业务场景（内存分析、通信分析、算子分析等）的复杂度激增，单一的 `Orchestrator` 容易成为维护瓶颈（臃肿的单体路由）。

**核心结论：不建议采用“去中心化对话式”的多 Agent（如 AutoGen/CrewAI），而应采用“主从/分层式的智能体工作流 (Agentic Workflow)”。**

### 2.1 为什么拒绝“去中心化对话式”架构？
1. **丧失确定性**：严肃的工业诊断场景不允许 Agent 自由闲聊导致逻辑跳跃或死循环。
2. **调试灾难**：状态机混乱，前端无法渲染明确的进度条。
3. **Token 消耗失控**：Agent 之间频繁传递海量日志上下文。

### 2.2 推荐架构：主从/分层协作模式
* **Orchestrator (父 Agent / 调度者)**：
  * 负责全局意图识别、生成顶层 `ExecutionPlan`。
  * 维护全局状态机，负责向前端发送规范的 SSE 流事件。
* **Expert Sub-Agents (专家子 Agent / 执行者)**：
  * 将 `_handle_diagnosis` 或特定领域的分析剥离为独立的子 Agent（如：DiagnosisAgent, KnowledgeAgent）。
  * 拥有专属的 `System Prompt` 和受限的 MCP 工具集。
  * 专注于执行特定任务，完成后向数据库写入 `Evidence`，并返回结构化结果。

---

## 三、 交互规范：Human-in-the-loop (人工介入)

在子 Agent 执行过程中（如需用户选择剧本、补充缺失参数），必须遵循**“子 Agent 提申请，父 Agent 发通知”**的中转/分发模式。

### 3.1 父 Agent 中转模式的优势
1. **统一 UI 协议**：前端只与 Orchestrator 保持单条 SSE 连接，无需处理复杂的路由。
2. **状态机一致**：Orchestrator 能够准确挂起（Suspend）对应的 `ExecutionStep`，更新数据库状态。
3. **策略拦截**：父 Agent 可以实施全局 `InteractionPolicy`，例如拦截高危工具调用，强制转为人工确认。

### 3.2 信号机制实现路径
1. **发出信号**：子 Agent 发现缺参数时，终止执行并返回一个 `Requirement` 信号（内部包含构建好的 `PendingInput` 详情与自身上下文快照）。
2. **父节点挂起**：Orchestrator 捕获信号，将 `PendingInput` 落库，并通过 SSE 发送 `user_input_required` 事件，挂起当前会话。
3. **唤醒与路由**：用户提交输入后，Orchestrator 接收请求，根据 `PendingInput` metadata 中的路由信息，带着用户的输入精准唤醒对应的子 Agent 恢复执行。

---

## 四、 Token 消耗优化：基于“黑板模式”的上下文管理

多 Agent 架构极易造成 Token 爆炸。依托本项目优秀的 `SessionStore`，可以实现**高智商、低 Token** 的协作：

### 4.1 避免“全量复制”，采用“证据驱动” (Evidence-Driven)
不再向子 Agent 传递包含几十轮历史的 `messages` 数组，而是：
* Orchestrator 向子 Agent 派发任务时，只传递 **精炼的任务目标** + **相关的 Evidence ID 列表/摘要**。
* 子 Agent 仅关注自己领域的数据。

### 4.2 避免“套娃式推理”，采用“黑板模式” (Blackboard Pattern)
* **数据库即共享内存**：子 Agent A (如：检索专家) 查出结果后，不通过语言跟 子 Agent B (如：诊断专家) 讲，而是直接将 `RAG_EVIDENCE` 写入 DB。
* 子 Agent B 执行时，直接从 DB（黑板）加载结构化证据，避免了中间层层 Prompt 转述带来的 Token 浪费。

### 4.3 工具与状态隔离
* **细分工具集**：不在主 Prompt 里塞入所有 20 个 MCP Tool Schema，每个领域的专家 Agent 仅携带自己需要的 3-5 个专属 Schema。
* **交互状态快照**：等待用户输入时，将 Agent 当前推理的精简草稿存入 `PendingInput.metadata`，恢复时拼接用户回复继续推理，避免从头重跑。

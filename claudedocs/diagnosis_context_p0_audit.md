# Diagnosis Context P0 基线审计

## 1. 审计目标

本文件对应 `claudedocs/workflow_diagnosis_context.md` 的 P0：基线审计与范围冻结。

P0 不执行功能实现代码修改，目标是确认后续 `DiagnosisAgent` 工业级上下文机制的实施入口、当前问题、现有边界和工作区风险。

## 2. 工作区状态摘要

当前工作区存在大量已修改和未跟踪文件，后续实施前必须区分源码变更、文档变更、运行产物和外部组件目录。

### 2.1 本次上下文机制相关文档

已新增：

- `docs/diagnosis_context_requirements.md`
- `docs/diagnosis_context_design.md`
- `claudedocs/workflow_diagnosis_context.md`
- `claudedocs/diagnosis_context_p0_audit.md`

这些属于本轮 diagnosis context 设计/工作流/P0 审计产物。

### 2.2 需要避免作为源码提交的运行产物

工作区中存在大量运行产物或本地文件：

- `agent-service/sessions/sessions.db`
- `**/__pycache__/**`
- `*.pyc`
- `.DS_Store`

这些不应作为 diagnosis context 功能源码提交，除非后续用户明确要求保留调试数据库。

### 2.3 已存在的较大历史/并行改动

当前工作区还有较多与此前 Agent Harness 改造相关的文件修改或新增，例如：

- `README.md`
- `docs/requirements.md`
- `docs/design.md`
- `docs/startup.md`
- `docs/architecture_evolution.md`
- `agent-service/src/adapters/mcp_gateway.py`
- `agent-service/src/adapters/mcp_response_parser.py`
- `agent-service/src/adapters/rag_client.py`
- `agent-service/src/core/orchestrator.py`
- `agent-service/src/core/intent_router.py`
- `agent-service/src/core/agents/__init__.py`
- `agent-service/src/core/agents/base.py`
- `agent-service/tests/core/agents/test_base.py`
- `agent-service/tests/core/test_orchestrator_multi_agent.py`
- `mcp_service_code/`
- `rag_code/`

这些不应被误认为本次 P0 产生的实现代码变更。后续实现 diagnosis context 时，应在提交切分中明确区分既有改造与新增上下文机制。

## 3. 当前主链路确认

### 3.1 Orchestrator 主入口

当前 `agent-service/src/core/orchestrator.py` 中：

- `/api/stream/message` 对应的主逻辑是 `Orchestrator.handle_message(...)`。
- `/api/stream/continue` 对应的主逻辑是 `Orchestrator.continue_with_input(...)`。
- diagnosis/profiling intent 进入 `_handle_diagnosis(...)`。
- `_handle_diagnosis(...)` 调用：

```python
blackboard = self._build_blackboard_for_diagnosis(session_id, extracted)
result = await self.agents["diagnosis"].run(session_id, search_step.id if search_step else "", message, blackboard)
```

### 3.2 DiagnosisAgent 是当前 diagnosis 子 Agent

当前 `Orchestrator.__init__` 中注册：

```python
self.agents = {
    "diagnosis": DiagnosisAgent(self.mcp_gateway, self.session_store, self.policy, self.llm_assistant),
    "knowledge": KnowledgeAgent(self.rag_client, self.session_store)
}
```

因此后续 diagnosis context 的第一接入点应是：

- `agent-service/src/core/agents/diagnosis_agent.py`
- `agent-service/src/core/orchestrator.py`

### 3.3 MCP 调用边界

当前 `agent-service/src/adapters/mcp_gateway.py` 仍符合 meta-tool gateway 边界：

- `search_profiler_tools(...)` 调 MCP 顶层 meta-tool `search_profiler_tools`。
- `execute_profiler_tool(...)` 调 MCP 顶层 meta-tool `execute_profiler_tool`，并传入 internal tool name 和 arguments。
- `ensure_tools_loaded(...)` 校验 required meta tools。

后续实现不得绕过 `MCPGateway` 直接调用 MCP internal tools。

## 4. 当前问题复核

### 4.1 DiagnosisAgent 仍使用薄 context

当前 `DiagnosisAgent.run(...)` 中：

- 只从 `blackboard.get("extracted", {})` 获取上下文。
- LLM playbook selection 使用 `{"extracted": extracted}`。
- 初始参数解析使用 `{"message": goal, **extracted}`。
- pending metadata 中保存的是薄 `context` dict，例如：

```python
{"message": goal, "path": extracted.get("path"), "selected_playbook": ...}
```

这与需求文档中的问题一致：当前没有持久化 diagnosis-level `DiagnosisContext`。

### 4.2 Resume 仍从 pending metadata 恢复薄 context

当前 `DiagnosisAgent.resume(...)` 中：

```python
context = suspended_metadata.get("context", {})
```

用户补参时：

- 先解析 dict/JSON；
- 单缺参走 fast path；
- 否则调用 `llm_assistant.extract_parameters_by_schema(...)`；
- 该调用目前未传入完整 diagnosis context。

这会导致 suspend/resume 后上下文信息变薄，无法充分利用前序 MCP 输出或参数 provenance。

### 4.3 Next step 参数解析仍依赖 message/path

当前 `DiagnosisAgent._execute_tool_and_check_next(...)` 中，next step 参数解析：

```python
next_args = self._resolve_step_arguments(next_step, {}, context)
next_args = await self.llm_assistant.extract_parameters(context.get("message", ""), next_step, next_args, context)
```

`_resolve_step_arguments(...)` 只处理：

- path aliases：`path/file_path/filepath/trace_path/trace_file/data_path`
- query aliases：`query/question/user_query/goal`

缺少：

- MCP output 参数写回；
- param provenance；
- CandidateSet；
- invalidated params 过滤；
- conflict handling；
- schema drift；
- compact context。

### 4.4 Orchestrator continue 当前绕过 operation queue

当前 `Orchestrator.continue_with_input(...)`：

- 直接读取 active pending；
- 保存用户输入 evidence；
- 直接 `resolve_pending_input(pending.id)`；
- 直接调用 `agent.resume(...)`。

这尚未满足 P0/P1 需求中的：

- pending input intent routing；
- session-level mutation serialization；
- FIFO operation queue；
- idempotency；
- stale queued operation validation。

### 4.5 Orchestrator 内仍存在旧/重复 MCP chain helper

`orchestrator.py` 中仍保留 `_execute_mcp_chain(...)`、`_pending_from_search(...)`、`_resolve_step_arguments(...)` 等 helper。当前 `_handle_diagnosis(...)` 已经委托 `DiagnosisAgent.run(...)`，这些 helper 是否仍被调用需后续在实施前进一步 grep/引用确认。

后续应避免在 Orchestrator 与 DiagnosisAgent 中各自维护一套 MCP step 参数解析逻辑，主逻辑应收敛到 `DiagnosisAgent` + `ParameterResolver`。

## 5. 配置风险

`agent-service/config/config.yaml` 当前包含明文 Claude provider API key：

```yaml
llm:
  providers:
    claude:
      api_key: "..."
```

这是安全风险。P0 本身不修改配置，但后续提交前建议改为环境变量引用，例如：

```yaml
api_key: "${CLAUDE_API_KEY}"
```

并确认不会把真实密钥提交到远端。

## 6. 后续实施范围冻结

### 6.1 Phase 1 的优先源码范围

后续 P1/P2/P3/P4 首批应优先修改：

- `agent-service/src/core/diagnosis/` 新增包
- `agent-service/src/core/agents/diagnosis_agent.py`
- `agent-service/src/core/mcp_llm_assistant.py`
- `agent-service/src/storage/session_store.py`
- `agent-service/src/core/orchestrator.py`
- `agent-service/tests/core/`
- `agent-service/tests/test_dynamic_mcp_orchestration.py`
- `agent-service/tests/test_orchestrator_llm_assistance.py`

### 6.2 暂不作为首批实现范围

P1-P4 不应优先修改：

- MCP service internal tools；
- MCP 顶层工具暴露方式；
- RAG service 内部实现；
- 前端 UI 大改；
- 完整 replay；
- MCP internal tool 风险等级分类。

### 6.3 必须保留的现有行为

后续实现必须保持：

1. diagnosis/profiling 仍通过 `MCPGateway` meta-tools。
2. LLM assistance 失败时降级 deterministic 行为。
3. 普通知识问答仍走 `KnowledgeAgent` / RAG，不应被 diagnosis pending 错误拦截。
4. `user_input_required` 事件保持向后兼容，即新增字段不能破坏旧前端基本渲染。
5. SQLite schema 变更使用非破坏性迁移。

## 7. P0 验收结论

P0 已完成以下确认：

- 当前工作区状态已审计。
- 运行产物与源码/文档变更已区分。
- 当前 diagnosis 主链路入口已确认。
- `DiagnosisAgent` 薄 context 问题已复核。
- `resume` 薄 context 问题已复核。
- next step 参数解析局限已复核。
- `Orchestrator.continue_with_input` 直接 resume、未经过 operation queue 的问题已复核。
- `MCPGateway` meta-tool 边界已确认，后续必须保留。
- 明文 API key 配置风险已记录。

下一步可进入 P1：新增 `agent-service/src/core/diagnosis/` 包并实现核心模型与 JSON 序列化。

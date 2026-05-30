# AI Profiling Agent Service

AI模型训练推理调试工具定制化Agent后端服务。

## 项目结构

```
agent-service/
├── src/
│   ├── core/                    # 核心组件
│   │   ├── orchestrator.py      # 动态 MCP playbook 编排
│   │   ├── intent_router.py     # 意图路由
│   │   ├── interaction_policy.py # 自动执行/用户确认策略
│   │   ├── mcp_llm_assistant.py # 受控 LLM 辅助
│   │   └── report_generator.py  # 报告生成
│   ├── llm/                     # LLM适配层
│   │   ├── llm_router.py        # LLM路由器
│   │   ├── claude_adapter.py
│   │   ├── openai_adapter.py
│   │   └── local_adapter.py
│   ├── mcp/                     # MCP客户端
│   │   ├── client.py            # 客户端主类
│   │   └── transports/          # 传输层实现
│   │       ├── http_transport.py
│   │       ├── stdio_transport.py
│   │       ├── sse_transport.py
│   │       └── websocket_transport.py
│   ├── knowledge/               # 知识库
│   │   ├── retriever.py         # 混合检索
│   │   └── vector_store.py      # 向量存储
│   ├── case_lib/                # 案例库
│   │   └── manager.py
│   ├── error_handling/          # 错误处理
│   │   ├── retry.py             # 重试机制
│   │   ├── circuit_breaker.py   # 熔断器
│   │   ├── handler.py           # 错误处理器
│   │   └── fallback.py          # 降级策略
│   ├── observability/           # 可观测性
│   │   ├── logging_config.py    # 结构化日志
│   │   ├── metrics.py           # Prometheus指标
│   │   └── health.py            # 健康检查
│   ├── storage/                 # 存储
│   │   ├── session_store.py
│   │   └── config_store.py
│   ├── api/                     # API路由
│   │   ├── routes/
│   │   │   ├── sessions.py
│   │   │   ├── streaming.py     # SSE流式API
│   │   │   └── error_handling.py
│   │   └── sse.py               # SSE工具
│   └── models/                  # 数据模型
├── config/
│   └── config.yaml              # 主配置
├── knowledge/                   # 知识文档
├── cases/                       # 案例存储
├── sessions/                    # 会话存储
└── tests/                       # 测试
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/config.yaml`：

```yaml
llm:
  default_provider: "claude"
  providers:
    claude:
      api_key: "${CLAUDE_API_KEY}"
      model: "claude-sonnet-4-6"

mcp:
  transport: "stdio"
  command: "python"
  args: ["main.py", "--transport", "stdio"]
  cwd: "D:/Project/新建文件夹/mcp"

rag:
  enabled: true
  base_url: "http://127.0.0.1:8001"
  retrieve_path: "/api/v1/retrieve"
  qa_path: "/api/v1/qa"
```

或使用环境变量：

```bash
export CLAUDE_API_KEY="your-api-key"
```

### 3. 启动服务

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## API端点

### 核心API

| 端点 | 方法 | 说明 |
|-----|------|------|
| `/api/sessions` | POST | 创建会话 |
| `/api/sessions/{id}` | GET | 获取会话 |
| `/api/sessions` | GET | 列出会话 |

### 流式API (SSE)

| 端点 | 方法 | 说明 |
|-----|------|------|
| `/api/stream/message` | POST | 流式发送消息 |
| `/api/stream/continue` | POST | 流式继续分析 |
| `/api/stream/connect/{session_id}` | GET | SSE连接 |

### 系统状态

| 端点 | 方法 | 说明 |
|-----|------|------|
| `/health` | GET | 完整健康检查 |
| `/live` | GET | 存活探针 |
| `/ready` | GET | 就绪探针 |
| `/metrics` | GET | Prometheus指标 |

### 错误处理

| 端点 | 方法 | 说明 |
|-----|------|------|
| `/api/error-handling/circuit-breakers` | GET | 熔断器状态 |
| `/api/error-handling/circuit-breakers/{name}/reset` | POST | 重置熔断器 |
| `/api/error-handling/errors/stats` | GET | 错误统计 |

## SSE事件类型

流式API返回以下事件类型：

| 事件 | 说明 |
|-----|------|
| `message_start` | 消息开始 |
| `message_delta` | 消息片段 |
| `message_end` | 消息结束 |
| `execution_plan_created` | 已创建本轮执行计划 |
| `execution_step_started` | 执行步骤开始 |
| `execution_step_completed` | 执行步骤完成 |
| `execution_step_failed` | 执行步骤失败 |
| `intent_detected` | 意图识别结果 |
| `rag_retrieval` | RAG 检索状态或结果 |
| `mcp_tool_start` | MCP 工具开始执行 |
| `mcp_tool_result` | MCP 工具返回结果 |
| `analysis_result` | 分析结果 |
| `report_ready` | 报告已生成 |
| `user_input_required` | 需要用户输入 |
| `error` | 错误 |

## MCP传输配置

### HTTP传输

```yaml
mcp:
  transport: "stdio"
  command: "python"
  args: ["main.py", "--transport", "stdio"]
  cwd: "D:/Project/新建文件夹/mcp"

rag:
  enabled: true
  base_url: "http://127.0.0.1:8001"
  retrieve_path: "/api/v1/retrieve"
  qa_path: "/api/v1/qa"
  timeout: 30
```

### Stdio传输

```yaml
mcp:
  transport: "stdio"
  command: "python"
  args: ["-m", "my_mcp_server"]
  env:
    DEBUG: "1"
```

### SSE传输

```yaml
mcp:
  transport: "sse"
  server_url: "https://mcp-server.example.com"
  api_key: "your-api-key"
```

### WebSocket传输

```yaml
mcp:
  transport: "websocket"
  server_url: "ws://localhost:5000"
  api_key: "your-api-key"
  reconnect: true
  reconnect_interval: 5
```

## 动态 MCP Playbook 编排

Profiling 诊断不再由本地 YAML 静态流程定义。后端会先加载 MCP `tools/list`，再调用 `search_profiler_tools` 搜索或选择 playbook，并根据 MCP 返回的 `initial_step` / `next_step` 逐步调用 `execute_profiler_tool`。LLM 只作为受控辅助，用于搜索 query 改写、明确语境下的 playbook 选择、候选排序和 schema 参数抽取。

## 错误处理

### 重试机制

```python
from src.error_handling import retry

@retry(max_attempts=3, base_delay=1.0)
async def my_operation():
    ...
```

### 熔断器

```python
from src.error_handling import circuit_breaker

@circuit_breaker(name="mcp_service", failure_threshold=5)
async def call_mcp():
    ...
```

### 降级策略

```python
from src.error_handling import with_fallback

@with_fallback("mcp_tool_parse_data")
async def parse_data(path):
    ...
```

## 可观测性

### 日志配置

```yaml
log:
  level: INFO
  json_format: false  # 生产环境设为true
  file: /var/log/agent.log
```

### Prometheus指标

- `agent_http_requests_total` - HTTP请求总数
- `agent_mcp_tool_calls_total` - MCP工具调用
- `agent_llm_calls_total` - LLM调用
- `agent_dag_flow_executions_total` - DAG流程执行
- `agent_errors_total` - 错误统计
- `agent_circuit_breaker_state` - 熔断器状态

## 开发

### 运行测试

```bash
pytest tests/ -v
```

### 代码风格

```bash
black src/
isort src/
```

## License

MIT

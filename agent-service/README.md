# AI Profiling Agent Service

AI模型训练推理调试工具定制化Agent后端服务。

## 项目结构

```
agent-service/
├── src/
│   ├── core/                    # 核心组件
│   │   ├── dag/                 # DAG工作流引擎
│   │   │   ├── engine.py        # 核心引擎
│   │   │   ├── executors.py     # 步骤执行器
│   │   │   └── dag_engine.py    # DAG引擎主类
│   │   ├── intent_recognizer.py # 意图识别
│   │   ├── state_machine.py     # 状态机
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
│   │   │   ├── messages.py
│   │   │   ├── streaming.py     # SSE流式API
│   │   │   └── error_handling.py
│   │   └── sse.py               # SSE工具
│   └── models/                  # 数据模型
├── config/
│   ├── config.yaml              # 主配置
│   └── flows.yaml               # DAG流程定义
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
  transport: "http"
  server_url: "http://localhost:5000"
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
| `/api/sessions/{id}/messages` | POST | 发送消息 |

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
| `analysis_result` | 分析结果 |
| `user_input_required` | 需要用户输入 |
| `error` | 错误 |

## MCP传输配置

### HTTP传输

```yaml
mcp:
  transport: "http"
  server_url: "http://localhost:5000"
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

## DAG工作流

流程定义在 `config/flows.yaml`：

```yaml
flows:
  full_analysis:
    entry_point: parse_data
    steps:
      parse_data:
        type: mcp_tool
        params:
          data_path: "${input.data_path}"
        outputs:
          data_id: "$.data_id"
        next: get_overview
      # ... 更多步骤
```

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

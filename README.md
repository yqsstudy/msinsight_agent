# AI Profiling MCP 定制化Agent

AI模型训练推理调试工具的定制化Agent服务，通过自然语言交互降低使用门槛，提供智能诊断和优化建议。

## 项目组成

```
msinsight_agent/
├── agent-service/     # 后端服务 (Python/FastAPI)
├── agent-web/         # 前端应用 (React/TypeScript)
└── docs/              # 文档
```

## 核心功能

- **自然语言交互**: 通过对话方式提交分析请求
- **智能诊断**: 自动检测问题类型，调用MCP工具分析
- **多轮引导**: 需要用户选择时提供清晰的选项和说明
- **知识沉淀**: 用户采纳建议后形成案例库
- **流式输出**: SSE实时推送分析结果

## 技术栈

### 后端
- Python 3.10+
- FastAPI
- LLM Router (Claude/OpenAI/本地模型)
- MCP Client (HTTP/Stdio/SSE/WebSocket)
- DAG工作流引擎
- Prometheus指标

### 前端
- React 18 + TypeScript
- Ant Design 5
- Zustand状态管理
- SSE流式通信

## 快速开始

### 1. 启动后端服务

```bash
cd agent-service
pip install -r requirements.txt

# 配置API Key
export CLAUDE_API_KEY="your-api-key"

# 启动服务
uvicorn src.main:app --reload --port 8000
```

### 2. 启动前端应用

```bash
cd agent-web
npm install
npm run dev
```

### 3. 访问应用

- 前端界面: http://localhost:5173
- API文档: http://localhost:8000/docs
- Prometheus指标: http://localhost:8000/metrics

## 文档

- [需求规格](docs/requirements.md)
- [系统设计](docs/design.md)
- [后端服务文档](agent-service/README.md)
- [前端应用文档](agent-web/README.md)

## 项目特性

### 工业级错误处理
- 指数退避重试机制
- 熔断器防止级联故障
- 优雅降级策略
- 完善的错误分类

### 可观测性
- 结构化JSON日志
- Prometheus指标
- 健康检查端点
- 熔断器状态监控

### 灵活配置
- 多LLM提供商支持
- 多MCP传输方式
- YAML配置文件

## License

MIT

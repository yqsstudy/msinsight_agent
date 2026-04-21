# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Profiling MCP Agent - A customized agent for AI model training/inference debugging tools. The project consists of:
- **agent-service/**: Python FastAPI backend with DAG workflow engine
- **agent-web/**: React TypeScript frontend with SSE streaming

## Development Commands

### Backend (agent-service/)
```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn src.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Run single test
pytest tests/test_dag_engine.py -v -k "test_execute_flow"

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

### Frontend (agent-web/)
```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Lint
npm run lint
```

## Architecture

### Backend Architecture

```
src/
├── core/dag/           # DAG workflow engine (key component)
│   ├── engine.py       # FlowContext, StepResult, ExpressionEvaluator
│   ├── executors.py    # Step executors with retry/circuit-breaker/fallback
│   └── dag_engine.py   # DAGEngine main class
├── error_handling/     # Industrial-grade error handling
│   ├── retry.py        # Exponential backoff retry
│   ├── circuit_breaker.py  # Circuit breaker pattern
│   ├── handler.py      # Error classification and handling
│   └── fallback.py     # Degradation strategies
├── mcp/transports/     # MCP client with multiple transport types
├── observability/      # Logging, metrics, health checks
└── api/routes/         # FastAPI routes including SSE streaming
```

### Key Design Patterns

1. **DAG Workflow Engine**: Analysis flows are defined in `config/flows.yaml`. Each step has a type (mcp_tool, decision, condition, parallel, user_input, report) and executors handle them with integrated error handling.

2. **Error Handling Layer**: Executors integrate retry → circuit-breaker → fallback chain. MCPToolExecutor and DecisionExecutor have full error handling integration.

3. **SSE Streaming**: Frontend uses `fetch` + `ReadableStream` for SSE. Events: `message_start`, `message_delta`, `message_end`, `user_input_required`, `analysis_result`, `error`.

4. **MCP Transports**: Supports HTTP, Stdio, SSE, WebSocket. Configured in `config/config.yaml` under `mcp.transport`.

### Configuration

- `config/config.yaml`: Main config (LLM providers, MCP transport, knowledge base)
- `config/flows.yaml`: DAG flow definitions

Environment variables for API keys:
- `CLAUDE_API_KEY`
- `OPENAI_API_KEY`

### API Endpoints

- `POST /api/stream/message` - SSE streaming message
- `POST /api/stream/continue` - Continue analysis with user input
- `GET /health`, `/live`, `/ready` - Health checks
- `GET /metrics` - Prometheus metrics
- `GET /api/error-handling/circuit-breakers` - Circuit breaker status

## Code Conventions

- Backend uses async/await throughout
- Executors return `StepResult` with status (COMPLETED, FAILED, WAITING_INPUT)
- Error handling: use decorators `@retry`, `@circuit_breaker`, `@with_fallback` from `src.error_handling`
- Observability: import from `src.observability` for logging and metrics

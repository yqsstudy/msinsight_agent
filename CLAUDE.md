# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Profiling MCP Agent - A customized agent for AI model training/inference debugging tools. The project consists of:
- **agent-service/**: Python FastAPI backend with dynamic MCP playbook orchestration
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

# Run focused orchestrator tests
pytest tests/test_dynamic_mcp_orchestration.py tests/test_orchestrator_llm_assistance.py -v

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
├── core/
│   ├── orchestrator.py          # Agent Harness state machine and dynamic MCP orchestration
│   ├── intent_router.py         # Intent routing and extraction
│   ├── interaction_policy.py    # Auto-execution and user confirmation policy
│   ├── mcp_llm_assistant.py     # Controlled LLM assistance for playbook search/selection/params
│   └── report_generator.py      # Report generation
├── adapters/
│   ├── mcp_gateway.py           # MCP meta-tool gateway: search_profiler_tools / execute_profiler_tool
│   └── mcp_response_parser.py   # MCP structured/text response parsing
├── error_handling/              # Retry, circuit breaker, fallback primitives
├── mcp/transports/              # MCP client transports
├── observability/               # Logging, metrics, health checks
└── api/routes/                  # FastAPI routes including SSE streaming
```

### Key Design Patterns

1. **Dynamic MCP Playbook Orchestration**: Profiling diagnosis is driven by MCP runtime responses. The backend calls `search_profiler_tools`, then executes the MCP-provided `initial_step` and follows subsequent `next_step` values from `execute_profiler_tool`.

2. **Controlled LLM Assistance**: LLM can rewrite playbook search queries, select a playbook from `tools/list` metadata when unambiguous, rank MCP-provided candidates, and extract schema-limited parameters. It must not invent tools/playbooks or bypass MCP side-effect confirmation.

3. **SSE Streaming**: Frontend uses `fetch` + `ReadableStream` for SSE. Events: `message_start`, `message_delta`, `message_end`, `user_input_required`, `analysis_result`, `error`.

4. **MCP Transports**: Supports HTTP, Stdio, SSE, WebSocket. Configured in `config/config.yaml` under `mcp.transport`.

### Configuration

- `config/config.yaml`: Main config (LLM providers, LLM assistance, MCP transport, knowledge base)

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
- MCP execution must go through `MCPGateway` meta-tools, not hardcoded internal playbook steps
- LLM assistance is advisory and must degrade to deterministic behavior on failure
- Error handling: use decorators `@retry`, `@circuit_breaker`, `@with_fallback` from `src.error_handling` where appropriate
- Observability: import from `src.observability` for logging and metrics

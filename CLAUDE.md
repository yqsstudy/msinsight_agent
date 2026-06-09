# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Profiling MCP Agent is a multi-part system for AI model training/inference performance debugging through natural-language interaction.

Primary components:
- **agent-service/**: Python FastAPI backend that orchestrates diagnosis, MCP playbooks, LLM assistance, RAG retrieval, session storage, and SSE streaming.
- **agent-web/**: React + TypeScript frontend for chat, session history, execution-plan display, system status, and SSE consumption.
- **mcp_service_code/ms_mcp/**: Python MCP server that exposes profiler analysis through two meta-tools and bridges to the C++ profiling backend.
- **rag_code/ms_rag/**: Standalone FastAPI + RAG service for Ascend/MindStudio performance documentation QA.
- **docs/**: Product/design documentation for the root agent project.

## Development Commands

Run commands from the listed component directory unless noted.

### Backend agent service (`agent-service/`)

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn src.main:app --reload --port 8000

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_dynamic_mcp_orchestration.py -v

# Run a single test case
pytest tests/test_dynamic_mcp_orchestration.py::test_name -v

# Run focused orchestration / LLM-assistance tests
pytest tests/test_dynamic_mcp_orchestration.py tests/test_orchestrator_llm_assistance.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Format imports and code
isort src/ tests/
black src/ tests/
```

### Frontend agent web (`agent-web/`)

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Lint
npm run lint

# Preview production build
npm run preview
```

The frontend expects the backend at `VITE_API_BASE` (commonly `http://localhost:8000`).

### MCP service (`mcp_service_code/ms_mcp/`)

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_navigator.py -v

# Start stdio MCP server
MSINSIGHT_MCP_TRANSPORT=stdio python main.py

# Start SSE MCP server
MSINSIGHT_MCP_TRANSPORT=sse MSINSIGHT_MCP_HOST=127.0.0.1 MSINSIGHT_MCP_PORT=8765 python main.py
```

Common C++ backend environment variables:
```bash
MSINSIGHT_CPP_BACKEND_HOST=127.0.0.1
MSINSIGHT_CPP_BACKEND_PORT=9000
MSINSIGHT_CPP_AUTO_START_BINARY=/path/to/profiler_server
```

### RAG service (`rag_code/ms_rag/`)

```bash
# Install backend dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install

# Build or rebuild indexes
python scripts/build_index.py
python scripts/build_index.py --force

# Run service
python -m src.main

# Run tests
pytest tests/ -v
```

## Architecture

### End-to-end flow

1. `agent-web` sends chat input to `agent-service` via SSE endpoints.
2. `agent-service` identifies intent, creates an execution plan, optionally retrieves RAG context, and routes profiling work through `MCPGateway`.
3. `MCPGateway` talks to `mcp_service_code/ms_mcp` through configured MCP transport (`stdio`, `http`, `sse`, or `websocket`).
4. The MCP service exposes only meta-tools and enforces playbook dependencies before calling internal profiler tools or the C++ backend.
5. Results stream back to the frontend as SSE events and may become reports, evidence, session state, or case-library entries.

### Backend agent service (`agent-service/src/`)

Key areas:
- `api/routes/streaming.py`: SSE chat and continuation endpoints.
- `core/orchestrator.py`: Main agent harness state machine and dynamic MCP playbook orchestration.
- `core/intent_router.py`: Intent classification/routing and extraction.
- `core/interaction_policy.py`: Auto-execution vs user-confirmation policy.
- `core/mcp_llm_assistant.py`: Controlled LLM assistance for playbook search, selection, ranking, and schema-limited parameter extraction.
- `adapters/mcp_gateway.py`: MCP meta-tool gateway; use this instead of hardcoding playbook/tool calls.
- `adapters/mcp_response_parser.py`: Parses structured/text MCP responses.
- `llm/`: Provider adapters and routing for Claude, OpenAI, and local models.
- `knowledge/` and `adapters/rag_client.py`: RAG retrieval integration.
- `storage/`: Session/config persistence.
- `observability/`: Logging, metrics, and health checks.
- `error_handling/`: Retry, circuit breaker, and fallback decorators/primitives.

Important backend rules:
- Profiling diagnosis is **dynamic MCP playbook orchestration**: call `search_profiler_tools`, execute the returned `initial_step`, then follow MCP-provided `next_step` values from `execute_profiler_tool`.
- LLM assistance is advisory only. It may rewrite search queries, choose/rank known playbooks, and extract schema-limited parameters, but must not invent tools/playbooks or bypass MCP side-effect confirmation.
- MCP execution must go through `MCPGateway` meta-tools, not direct internal playbook/tool calls.
- LLM assistance must degrade to deterministic behavior on failures.

### MCP service (`mcp_service_code/ms_mcp/`)

The MCP server is a Progressive Disclosure Meta-Tool Gateway:
- Exposes only `search_profiler_tools` and `execute_profiler_tool` to AI clients.
- Registers internal atomic tools via decorators under `tools/`.
- Loads YAML playbooks from `senario/` through `mapping/registry.py`.
- Tracks prerequisites, progress, and context through `state/session.py`, `state/context.py`, and `state/navigator.py`.
- Bridges trace/timeline/cluster tools to the C++ profiling backend over WebSocket.
- Handles PyTorch memory snapshot analysis in-process through `pt_snap/` and `tools/pt_snap/`.

When adding MCP capability, update the internal tool, metadata, parameter validation, and relevant playbook rather than exposing a new top-level MCP tool.

### Frontend (`agent-web/src/`)

Key areas:
- `services/api.ts`: API client and SSE stream parsing with `fetch` + `ReadableStream`.
- `stores/`: Zustand state for chat/session/UI state.
- `components/` and `pages/`: Chat UI, execution plan/step display, session list, and system status.
- `types/`: Shared TypeScript types for events, sessions, reports, and status.

SSE event names used by the UI include `message_start`, `message_delta`, `message_end`, `execution_plan_created`, `execution_step_started`, `execution_step_completed`, `execution_step_failed`, `intent_detected`, `rag_retrieval`, `mcp_tool_start`, `mcp_tool_result`, `analysis_result`, `report_ready`, `user_input_required`, and `error`.

### RAG service (`rag_code/ms_rag/`)

The RAG service is a separate FastAPI application with:
- `RAGPipeline` combining cache, embeddings, hybrid retrieval, reranking, graph expansion, context building, and LLM generation.
- Chroma vector retrieval + BM25 keyword retrieval.
- L1/L2/L3 cache layers for exact QA, semantic QA, and query embeddings.
- SSE QA endpoint and retrieval endpoints consumed by `agent-service` when configured.

Indexes and persistent data are generated under `data/` by `scripts/build_index.py`.

## Configuration

### Agent service

Main config: `agent-service/config/config.yaml`

Important sections:
- `llm`: providers, models, API-key environment references.
- `llm_assistance`: controlled LLM assistance behavior.
- `mcp`: transport and server settings.
- `rag`: optional RAG service base URL and endpoint paths.

Common environment variables:
- `CLAUDE_API_KEY`
- `OPENAI_API_KEY`

### MCP service

Settings are environment-driven with `MSINSIGHT_` prefixes. Common variables:
- `MSINSIGHT_MCP_TRANSPORT`: `stdio`, `sse`, or `websocket`
- `MSINSIGHT_MCP_HOST`, `MSINSIGHT_MCP_PORT`
- `MSINSIGHT_CPP_BACKEND_HOST`, `MSINSIGHT_CPP_BACKEND_PORT`
- `MSINSIGHT_CPP_AUTO_START_BINARY`
- `MSINSIGHT_LOG_LEVEL`

### RAG service

Main configs live under `rag_code/ms_rag/config/`. Typical LLM variables include:
- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_API_KEY`
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`
- `LLM_BASE_URL` for compatible APIs/proxies

## API Endpoints

### Agent service

- `POST /api/stream/message` - stream a new chat message.
- `POST /api/stream/continue` - continue analysis after user input.
- `GET /health`, `/live`, `/ready` - health checks.
- `GET /metrics` - Prometheus metrics.
- `GET /api/error-handling/circuit-breakers` - circuit breaker status.

### RAG service

- `POST /api/v1/qa` - synchronous QA.
- `POST /api/v1/qa/stream` - streaming QA.
- `POST /api/v1/retrieve` - retrieve relevant documents.
- `GET /api/v1/cache/stats` - cache statistics.
- `POST /api/v1/cache/clear` - clear cache.
- `GET /api/v1/health` - RAG service health.

## Code Conventions

- Backend code uses async/await throughout.
- Match existing provider/router/gateway abstractions instead of adding direct cross-layer calls.
- Use `@retry`, `@circuit_breaker`, and `@with_fallback` from `src.error_handling` for operations that need resilience.
- Import logging/metrics/health primitives from `src.observability`.
- Keep playbook-driven behavior in YAML and registry/state abstractions; avoid hardcoding MCP step order in the agent service.
- Generated caches, SQLite session databases, build outputs, and `__pycache__` files are present in the working tree; avoid treating them as source changes unless explicitly requested.

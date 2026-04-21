"""Prometheus指标定义"""

from prometheus_client import Counter, Histogram, Gauge, Info, Enum
from functools import wraps
import time

# ==================== HTTP请求指标 ====================

REQUEST_COUNT = Counter(
    "agent_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "agent_http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
)

REQUEST_IN_PROGRESS = Gauge(
    "agent_http_requests_in_progress",
    "HTTP requests currently in progress",
    ["method", "endpoint"]
)

# ==================== 会话指标 ====================

ACTIVE_SESSIONS = Gauge(
    "agent_active_sessions",
    "Number of active sessions"
)

SESSION_CREATED = Counter(
    "agent_sessions_created_total",
    "Total sessions created"
)

SESSION_DURATION = Histogram(
    "agent_session_duration_seconds",
    "Session duration in seconds",
    buckets=[60, 300, 600, 1800, 3600, 7200, 14400]
)

# ==================== MCP工具指标 ====================

MCP_TOOL_CALLS = Counter(
    "agent_mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool_name", "status"]
)

MCP_TOOL_LATENCY = Histogram(
    "agent_mcp_tool_latency_seconds",
    "MCP tool call latency in seconds",
    ["tool_name"],
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30]
)

MCP_TOOL_IN_PROGRESS = Gauge(
    "agent_mcp_tool_calls_in_progress",
    "MCP tool calls currently in progress",
    ["tool_name"]
)

# ==================== LLM指标 ====================

LLM_CALLS = Counter(
    "agent_llm_calls_total",
    "Total LLM API calls",
    ["provider", "model", "status"]
)

LLM_LATENCY = Histogram(
    "agent_llm_latency_seconds",
    "LLM API call latency in seconds",
    ["provider", "model"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60]
)

LLM_TOKENS_USED = Counter(
    "agent_llm_tokens_total",
    "Total tokens used",
    ["provider", "model", "type"]  # type: input/output
)

LLM_COST = Counter(
    "agent_llm_cost_dollars",
    "Total LLM cost in dollars",
    ["provider", "model"]
)

# ==================== DAG流程指标 ====================

DAG_FLOW_EXECUTIONS = Counter(
    "agent_dag_flow_executions_total",
    "Total DAG flow executions",
    ["flow_name", "status"]
)

DAG_FLOW_DURATION = Histogram(
    "agent_dag_flow_duration_seconds",
    "DAG flow execution duration in seconds",
    ["flow_name"],
    buckets=[1, 5, 10, 30, 60, 120, 300]
)

DAG_STEP_EXECUTIONS = Counter(
    "agent_dag_step_executions_total",
    "Total DAG step executions",
    ["flow_name", "step_name", "step_type", "status"]
)

# ==================== 知识库指标 ====================

KNOWLEDGE_SEARCHES = Counter(
    "agent_knowledge_searches_total",
    "Total knowledge base searches",
    ["status"]
)

KNOWLEDGE_SEARCH_LATENCY = Histogram(
    "agent_knowledge_search_latency_seconds",
    "Knowledge search latency in seconds",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1]
)

# ==================== 系统指标 ====================

APP_INFO = Info(
    "agent_app",
    "Application information"
)

APP_STATUS = Enum(
    "agent_app_status",
    "Application status",
    states=["starting", "running", "stopping", "error"]
)

# ==================== 错误处理指标 ====================

ERROR_TOTAL = Counter(
    "agent_errors_total",
    "Total errors by type",
    ["error_type", "severity"]
)

CIRCUIT_BREAKER_STATE = Gauge(
    "agent_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["circuit_name"]
)

FALLBACK_TOTAL = Counter(
    "agent_fallback_total",
    "Total fallback executions",
    ["strategy_name"]
)

RETRY_TOTAL = Counter(
    "agent_retries_total",
    "Total retry attempts",
    ["operation", "success"]
)

# ==================== 便捷函数 ====================

def track_request(method: str, endpoint: str):
    """追踪HTTP请求的装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            REQUEST_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
            start_time = time.time()
            status = "200"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "500"
                raise
            finally:
                duration = time.time() - start_time
                REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
                REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)
                REQUEST_IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()
        return wrapper
    return decorator


def track_mcp_tool(tool_name: str):
    """追踪MCP工具调用的装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            MCP_TOOL_IN_PROGRESS.labels(tool_name=tool_name).inc()
            start_time = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                MCP_TOOL_CALLS.labels(tool_name=tool_name, status=status).inc()
                MCP_TOOL_LATENCY.labels(tool_name=tool_name).observe(duration)
                MCP_TOOL_IN_PROGRESS.labels(tool_name=tool_name).dec()
        return wrapper
    return decorator


def track_llm_call(provider: str, model: str):
    """追踪LLM调用的装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                LLM_CALLS.labels(provider=provider, model=model, status=status).inc()
                LLM_LATENCY.labels(provider=provider, model=model).observe(duration)
        return wrapper
    return decorator


def record_llm_tokens(provider: str, model: str, input_tokens: int, output_tokens: int):
    """记录LLM token使用量"""
    LLM_TOKENS_USED.labels(provider=provider, model=model, type="input").inc(input_tokens)
    LLM_TOKENS_USED.labels(provider=provider, model=model, type="output").inc(output_tokens)


def record_dag_flow(flow_name: str, status: str, duration: float):
    """记录DAG流程执行"""
    DAG_FLOW_EXECUTIONS.labels(flow_name=flow_name, status=status).inc()
    DAG_FLOW_DURATION.labels(flow_name=flow_name).observe(duration)


def record_dag_step(flow_name: str, step_name: str, step_type: str, status: str):
    """记录DAG步骤执行"""
    DAG_STEP_EXECUTIONS.labels(
        flow_name=flow_name,
        step_name=step_name,
        step_type=step_type,
        status=status
    ).inc()


def set_app_info(version: str, commit: str = ""):
    """设置应用信息"""
    APP_INFO.info({
        "version": version,
        "commit": commit
    })


def set_app_status(status: str):
    """设置应用状态"""
    APP_STATUS.state(status)

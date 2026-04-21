"""Agent服务主入口"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from .api.routes import (
    sessions_router,
    messages_router,
    config_router,
    feedback_router,
    error_handling_router,
    streaming_router,
)
from .api.websocket import websocket_endpoint
from .storage import ConfigStore
from .observability import (
    setup_logging,
    get_logger,
    health_checker,
    set_app_info,
    set_app_status,
)


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化日志
    config = ConfigStore()
    log_level = config.get("log.level", "INFO")
    json_format = config.get("log.json_format", False)
    log_file = config.get("log.file")
    setup_logging(level=log_level, json_format=json_format, log_file=log_file)

    logger.info("Starting Agent Service...")

    # 设置应用信息
    set_app_info(version="0.1.0")
    set_app_status("starting")

    # 确保必要目录存在
    os.makedirs(config.get("session.storage_path", "./sessions"), exist_ok=True)
    os.makedirs(config.get("case_lib.storage_path", "./cases"), exist_ok=True)
    os.makedirs(config.get("knowledge.documents_path", "./knowledge/docs"), exist_ok=True)
    os.makedirs(config.get("knowledge.vector_store_path", "./knowledge/vectors"), exist_ok=True)

    set_app_status("running")
    logger.info("Agent Service started successfully")

    yield

    # 关闭时清理
    set_app_status("stopping")
    logger.info("Shutting down Agent Service...")


# 创建FastAPI应用
app = FastAPI(
    title="AI Profiling Agent Service",
    description="AI模型训练推理调试工具定制化Agent服务",
    version="0.1.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(sessions_router)
app.include_router(messages_router)
app.include_router(config_router)
app.include_router(feedback_router)
app.include_router(error_handling_router)
app.include_router(streaming_router)


# WebSocket端点
@app.websocket("/ws/{session_id}")
async def websocket_route(websocket: WebSocket, session_id: str):
    await websocket_endpoint(websocket, session_id)


# 健康检查端点
@app.get("/health")
async def health_check():
    """完整健康检查"""
    from .core.agent_controller_v2 import AgentControllerV2
    controller = app.state.controller if hasattr(app.state, "controller") else None

    if controller:
        result = await health_checker.check_all(
            session_store=controller.session_store,
            mcp_client=controller.mcp_client,
            llm_router=controller.llm_router,
            knowledge_retriever=controller.knowledge_retriever
        )
    else:
        result = {
            "status": "healthy",
            "message": "Service running, controller not initialized"
        }
    return result


@app.get("/live")
async def liveness():
    """存活检查 (Kubernetes liveness probe)"""
    return health_checker.get_liveness()


@app.get("/ready")
async def readiness():
    """就绪检查 (Kubernetes readiness probe)"""
    return health_checker.get_readiness()


# 挂载Prometheus指标端点
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# 根路径
@app.get("/")
async def root():
    return {
        "service": "AI Profiling Agent Service",
        "version": "0.1.0",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agent_service.src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

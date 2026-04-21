"""健康检查"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
import asyncio


class HealthStatus(Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """组件健康状态"""
    name: str
    status: HealthStatus
    message: str = ""
    details: Dict[str, Any] = None
    latency_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details or {},
            "latency_ms": self.latency_ms
        }


class HealthChecker:
    """健康检查器"""

    def __init__(self):
        self._checks: Dict[str, callable] = {}
        self._start_time = datetime.utcnow()

    def register_check(self, name: str, check_func: callable):
        """注册健康检查"""
        self._checks[name] = check_func

    async def check_database(self, session_store) -> ComponentHealth:
        """检查数据库连接"""
        try:
            start = datetime.utcnow()
            # 尝试执行简单操作
            session_store.list_all(limit=1)
            latency = (datetime.utcnow() - start).total_seconds() * 1000
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                message="Database connection OK",
                latency_ms=latency
            )
        except Exception as e:
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database error: {str(e)}"
            )

    async def check_mcp(self, mcp_client) -> ComponentHealth:
        """检查MCP服务"""
        try:
            start = datetime.utcnow()
            tools = await mcp_client.list_tools()
            latency = (datetime.utcnow() - start).total_seconds() * 1000

            if tools:
                return ComponentHealth(
                    name="mcp_service",
                    status=HealthStatus.HEALTHY,
                    message=f"MCP service OK, {len(tools)} tools available",
                    details={"tools_count": len(tools)},
                    latency_ms=latency
                )
            else:
                return ComponentHealth(
                    name="mcp_service",
                    status=HealthStatus.DEGRADED,
                    message="MCP service responding but no tools found",
                    latency_ms=latency
                )
        except Exception as e:
            return ComponentHealth(
                name="mcp_service",
                status=HealthStatus.UNHEALTHY,
                message=f"MCP service error: {str(e)}"
            )

    async def check_llm(self, llm_router) -> ComponentHealth:
        """检查LLM服务"""
        try:
            start = datetime.utcnow()
            # 简单的连接测试（不实际调用API）
            config = llm_router.config
            latency = (datetime.utcnow() - start).total_seconds() * 1000

            provider = config.get("default_provider", "unknown")
            providers = list(config.get("providers", {}).keys())

            return ComponentHealth(
                name="llm_service",
                status=HealthStatus.HEALTHY,
                message=f"LLM configured, default: {provider}",
                details={
                    "default_provider": provider,
                    "available_providers": providers
                },
                latency_ms=latency
            )
        except Exception as e:
            return ComponentHealth(
                name="llm_service",
                status=HealthStatus.UNHEALTHY,
                message=f"LLM config error: {str(e)}"
            )

    async def check_knowledge_base(self, knowledge_retriever) -> ComponentHealth:
        """检查知识库"""
        try:
            start = datetime.utcnow()
            # 检查知识库是否初始化
            if hasattr(knowledge_retriever, '_initialized') and knowledge_retriever._initialized:
                latency = (datetime.utcnow() - start).total_seconds() * 1000
                return ComponentHealth(
                    name="knowledge_base",
                    status=HealthStatus.HEALTHY,
                    message="Knowledge base initialized",
                    latency_ms=latency
                )
            else:
                return ComponentHealth(
                    name="knowledge_base",
                    status=HealthStatus.DEGRADED,
                    message="Knowledge base not initialized"
                )
        except Exception as e:
            return ComponentHealth(
                name="knowledge_base",
                status=HealthStatus.DEGRADED,
                message=f"Knowledge base error: {str(e)}"
            )

    async def check_all(
        self,
        session_store=None,
        mcp_client=None,
        llm_router=None,
        knowledge_retriever=None
    ) -> Dict[str, Any]:
        """执行所有健康检查"""
        checks: List[ComponentHealth] = []

        # 并行执行检查
        tasks = []

        if session_store:
            tasks.append(self.check_database(session_store))
        if mcp_client:
            tasks.append(self.check_mcp(mcp_client))
        if llm_router:
            tasks.append(self.check_llm(llm_router))
        if knowledge_retriever:
            tasks.append(self.check_knowledge_base(knowledge_retriever))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, ComponentHealth):
                    checks.append(result)
                elif isinstance(result, Exception):
                    checks.append(ComponentHealth(
                        name="unknown",
                        status=HealthStatus.UNHEALTHY,
                        message=str(result)
                    ))

        # 计算整体状态
        overall_status = self._calculate_overall_status(checks)

        # 计算运行时间
        uptime = (datetime.utcnow() - self._start_time).total_seconds()

        return {
            "status": overall_status.value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "uptime_seconds": uptime,
            "components": [c.to_dict() for c in checks]
        }

    def _calculate_overall_status(self, checks: List[ComponentHealth]) -> HealthStatus:
        """计算整体状态"""
        if not checks:
            return HealthStatus.HEALTHY

        statuses = [c.status for c in checks]

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    def get_liveness(self) -> Dict[str, Any]:
        """存活检查（Kubernetes liveness probe）"""
        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def get_readiness(self) -> Dict[str, Any]:
        """就绪检查（Kubernetes readiness probe）"""
        # 简单的就绪检查
        return {
            "status": "ready",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


# 全局健康检查器
health_checker = HealthChecker()

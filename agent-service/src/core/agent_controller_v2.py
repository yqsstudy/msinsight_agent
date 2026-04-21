"""Agent控制器 - 基于DAG引擎的新实现"""

import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import uuid

from ..llm import LLMRouter
from ..mcp import MCPClient
from ..knowledge import KnowledgeRetriever
from ..case_lib import CaseLibManager
from ..storage import SessionStore, ConfigStore
from .state_machine import AnalysisStateMachine, Event, State
from .intent_recognizer import IntentRecognizer, IntentType
from .report_generator import ReportGenerator
from .error_handler import ErrorHandler
from .dag import DAGEngine
from ..models import Session, Message, AnalysisContext, Option, AnalysisReport


class AgentControllerV2:
    """Agent控制器V2 - 基于DAG引擎"""

    # 意图到流程的映射
    INTENT_FLOW_MAP = {
        "full_analysis": "full_analysis",
        "targeted_analysis": None,  # 动态确定
        "memory": "memory_analysis",
        "communication": "communication_analysis",
    }

    def __init__(
        self,
        session_store: SessionStore = None,
        config_store: ConfigStore = None,
        llm_router: LLMRouter = None,
        mcp_client: MCPClient = None,
        knowledge_retriever: KnowledgeRetriever = None,
        case_manager: CaseLibManager = None,
        dag_engine: DAGEngine = None
    ):
        self.session_store = session_store or SessionStore()
        self.config_store = config_store or ConfigStore()

        # 初始化LLM路由器
        self.llm_router = llm_router or LLMRouter(self.config_store.get_llm_config())

        # 初始化MCP客户端
        self.mcp_client = mcp_client or MCPClient.from_config(
            self.config_store.get_mcp_config()
        )

        # 初始化知识库检索器
        self.knowledge_retriever = knowledge_retriever or KnowledgeRetriever()

        # 初始化案例库管理器
        self.case_manager = case_manager or CaseLibManager()

        # 初始化报告生成器
        self.report_generator = ReportGenerator(
            knowledge_retriever=self.knowledge_retriever,
            case_manager=self.case_manager
        )

        # 初始化DAG引擎
        self.dag_engine = dag_engine or DAGEngine(
            config_path="./config/flows.yaml",
            mcp_client=self.mcp_client,
            llm_router=self.llm_router,
            report_generator=self.report_generator
        )

        # 其他组件
        self.intent_recognizer = IntentRecognizer()
        self.error_handler = ErrorHandler()

        # 当前会话
        self.current_session: Optional[Session] = None

    def create_session(self, user_id: str = "default") -> Session:
        """创建新会话"""
        session = Session(
            id=str(uuid.uuid4()),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            state=State.IDLE.value,
            context=AnalysisContext()
        )
        self.session_store.save(session)
        self.current_session = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self.session_store.load(session_id)

    def set_session(self, session: Session):
        """设置当前会话"""
        self.current_session = session

    async def process_message(
        self,
        message: str,
        session_id: str = None,
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """
        处理用户消息

        Args:
            message: 用户消息
            session_id: 会话ID
            on_need_input: 需要用户输入时的回调

        Returns:
            处理结果
        """
        try:
            # 加载或创建会话
            if session_id:
                self.current_session = self.get_session(session_id)
                if not self.current_session:
                    raise ValueError(f"Session not found: {session_id}")
            elif not self.current_session:
                self.current_session = self.create_session()

            # 添加用户消息
            user_msg = Message(
                id=str(uuid.uuid4()),
                role="user",
                content=message,
                timestamp=datetime.now()
            )
            self.current_session.messages.append(user_msg)

            # 识别意图
            context = {
                "state": self.current_session.state,
                "pending_choices": self.current_session.context.pending_choices,
            }
            intent = self.intent_recognizer.recognize(message, context)

            # 根据意图类型处理
            if intent.type == IntentType.CHOICE:
                result = await self._handle_user_choice(intent)
            elif intent.type == IntentType.CONTINUE:
                result = await self._handle_continue()
            elif intent.type == IntentType.FEEDBACK:
                result = await self._handle_feedback(intent)
            else:
                result = await self._execute_flow(intent)

            # 更新会话
            self.current_session.updated_at = datetime.now()
            self.session_store.save(self.current_session)

            return result

        except Exception as e:
            return self.error_handler.handle(e, {"session_id": session_id})

    async def _execute_flow(self, intent) -> Dict[str, Any]:
        """执行DAG流程"""
        # 确定流程名称
        flow_name = self._get_flow_name(intent)

        # 构建参数
        params = {}
        if intent.data_path:
            params["data_path"] = intent.data_path
        if intent.target_problem:
            params["problem_type"] = intent.target_problem

        # 执行流程
        result = await self.dag_engine.execute(
            flow_name=flow_name,
            params=params,
            session_id=self.current_session.id
        )

        # 处理结果
        return self._process_flow_result(result)

    def _get_flow_name(self, intent) -> str:
        """获取流程名称"""
        if intent.type == IntentType.FULL_ANALYSIS:
            return "full_analysis"
        elif intent.type == IntentType.TARGETED_ANALYSIS:
            problem_type = intent.target_problem
            if problem_type == "memory":
                return "memory_analysis"
            elif problem_type == "communication":
                return "communication_analysis"
            else:
                return "full_analysis"
        else:
            return "full_analysis"

    def _process_flow_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """处理流程结果"""
        status = result.get("status")

        if status == "waiting_input":
            # 需要用户输入
            return {
                "response": result.get("question", "请选择："),
                "state": "WAITING_INPUT",
                "options": result.get("options", []),
                "reason": result.get("reason", "")
            }

        elif status == "completed":
            # 完成
            output = result.get("output", {})
            report = output.get("report")

            # 添加Agent消息
            agent_msg = Message(
                id=str(uuid.uuid4()),
                role="agent",
                content="分析完成",
                timestamp=datetime.now(),
                metadata={"report": report}
            )
            self.current_session.messages.append(agent_msg)

            return {
                "response": "分析完成",
                "state": "COMPLETED",
                "report": report
            }

        elif status == "error":
            return {
                "response": f"分析失败: {result.get('error', '未知错误')}",
                "state": "ERROR",
                "error": result.get("error")
            }

        else:
            return result

    async def _handle_user_choice(self, intent) -> Dict[str, Any]:
        """处理用户选择"""
        choice = intent.choice

        # 继续DAG流程
        result = await self.dag_engine.continue_with_input(
            session_id=self.current_session.id,
            user_input=choice
        )

        return self._process_flow_result(result)

    async def _handle_continue(self) -> Dict[str, Any]:
        """处理继续请求"""
        dag_context = self.dag_engine.get_context(self.current_session.id)
        if not dag_context:
            return {
                "response": "没有找到上次的分析记录",
                "state": "IDLE"
            }

        return {
            "response": "继续上次的分析...",
            "state": dag_context.status,
            "data": dag_context.state
        }

    async def _handle_feedback(self, intent) -> Dict[str, Any]:
        """处理反馈"""
        adopted = intent.adopted
        comment = intent.comment

        if self.current_session.context.case_id:
            self.case_manager.update_feedback(
                self.current_session.context.case_id,
                adopted,
                comment
            )

        return {
            "response": f"感谢反馈！{'已采纳建议' if adopted else '已记录意见'}",
            "state": self.current_session.state
        }

    def list_available_flows(self) -> List[str]:
        """列出可用流程"""
        return self.dag_engine.list_flows()

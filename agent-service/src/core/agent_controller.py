"""Agent控制器 - 统一协调各组件的核心逻辑"""

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
from .tool_orchestrator import ToolOrchestrator
from .intent_recognizer import IntentRecognizer, IntentType
from .report_generator import ReportGenerator
from .error_handler import ErrorHandler
from ..models import Session, Message, AnalysisContext, Option, AnalysisReport


class AgentController:
    """Agent控制器 - 协调LLM、工具编排、知识库、案例库"""

    def __init__(
        self,
        session_store: SessionStore = None,
        config_store: ConfigStore = None,
        llm_router: LLMRouter = None,
        mcp_client: MCPClient = None,
        knowledge_retriever: KnowledgeRetriever = None,
        case_manager: CaseLibManager = None
    ):
        self.session_store = session_store or SessionStore()
        self.config_store = config_store or ConfigStore()

        # 初始化LLM路由器
        self.llm_router = llm_router or LLMRouter(self.config_store.get_llm_config())

        # 初始化MCP客户端（支持多种传输方式）
        self.mcp_client = mcp_client or MCPClient.from_config(
            self.config_store.get_mcp_config()
        )

        # 初始化知识库检索器
        self.knowledge_retriever = knowledge_retriever or KnowledgeRetriever()

        # 初始化案例库管理器
        self.case_manager = case_manager or CaseLibManager()

        # 初始化各组件
        self.state_machine = AnalysisStateMachine()
        self.tool_orchestrator = ToolOrchestrator(self.mcp_client, self.state_machine)
        self.intent_recognizer = IntentRecognizer()
        self.report_generator = ReportGenerator()
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
        self.state_machine.reset()
        # 恢复状态机状态
        if session.state:
            self.state_machine.current_state = State(session.state)
        if session.context.analysis_results:
            self.state_machine.context = session.context.analysis_results

    async def process_message(
        self,
        message: str,
        session_id: str = None,
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """
        处理用户消息的主入口

        Args:
            message: 用户消息内容
            session_id: 会话ID（可选）
            on_need_input: 需要用户输入时的回调函数

        Returns:
            处理结果，包含响应、状态、报告等
        """
        try:
            # 加载或创建会话
            if session_id:
                self.current_session = self.get_session(session_id)
                if not self.current_session:
                    raise ValueError(f"Session not found: {session_id}")
            elif not self.current_session:
                self.current_session = self.create_session()

            self.set_session(self.current_session)

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
                "analysis_results": self.current_session.context.analysis_results
            }
            intent = self.intent_recognizer.recognize(message, context)

            # 根据意图类型处理
            if intent.type == IntentType.FULL_ANALYSIS:
                result = await self._handle_full_analysis(intent, on_need_input)
            elif intent.type == IntentType.TARGETED_ANALYSIS:
                result = await self._handle_targeted_analysis(intent, on_need_input)
            elif intent.type == IntentType.CHOICE:
                result = await self._handle_user_choice(intent, on_need_input)
            elif intent.type == IntentType.CONTINUE:
                result = await self._handle_continue()
            elif intent.type == IntentType.FEEDBACK:
                result = await self._handle_feedback(intent)
            else:
                result = await self._handle_question(message)

            # 更新会话状态
            self.current_session.state = self.state_machine.state
            self.current_session.updated_at = datetime.now()
            self.session_store.save(self.current_session)

            return result

        except Exception as e:
            error_type = self.error_handler.classify_error(e)
            error_result = self.error_handler.handle(error_type, {"error": str(e)}, e)
            return error_result

    async def _handle_full_analysis(
        self,
        intent,
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """处理全量分析请求"""
        data_path = intent.data_path

        # 更新上下文
        self.state_machine.set_context("data_path", data_path)
        self.state_machine.transition(Event.START)

        # 构建参数
        params = {"data_path": data_path}

        # 执行分析流程
        flow_result = await self.tool_orchestrator.execute_flow(
            "full_analysis",
            params,
            on_need_input
        )

        # 检查是否需要用户输入
        if flow_result.get("need_input"):
            return {
                "response": flow_result.get("question", "请选择："),
                "state": self.state_machine.state,
                "options": [opt.to_dict() for opt in flow_result.get("options", [])],
                "reason": flow_result.get("reason", "")
            }

        # 检查是否成功
        if not flow_result.get("success"):
            return {
                "response": f"分析失败: {flow_result.get('error', '未知错误')}",
                "state": self.state_machine.state,
                "error": flow_result.get("error")
            }

        # 生成报告
        report = await self._generate_report(flow_result.get("data", {}))

        # 添加Agent消息
        agent_msg = Message(
            id=str(uuid.uuid4()),
            role="agent",
            content=f"分析完成。检测到 {len(report.problems)} 个问题。",
            timestamp=datetime.now(),
            metadata={"report_id": report.id}
        )
        self.current_session.messages.append(agent_msg)

        return {
            "response": f"分析完成。检测到 {len(report.problems)} 个问题。",
            "state": self.state_machine.state,
            "report": report.to_dict()
        }

    async def _handle_targeted_analysis(
        self,
        intent,
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """处理定向分析请求"""
        data_path = intent.data_path
        problem_type = intent.target_problem

        # 更新上下文
        self.state_machine.set_context("data_path", data_path)
        self.state_machine.set_context("problem_type", problem_type)
        self.state_machine.transition(Event.START)

        # 根据问题类型选择流程
        flow_map = {
            "memory": "memory_analysis",
            "communication": "communication_analysis",
            "compute": "compute_analysis"
        }

        flow_name = flow_map.get(problem_type, "full_analysis")

        # 执行分析流程
        params = {
            "data_path": data_path,
            "problem_type": problem_type
        }

        flow_result = await self.tool_orchestrator.execute_flow(
            flow_name,
            params,
            on_need_input
        )

        # 检查是否需要用户输入
        if flow_result.get("need_input"):
            return {
                "response": flow_result.get("question", "请选择："),
                "state": self.state_machine.state,
                "options": [opt.to_dict() for opt in flow_result.get("options", [])],
                "reason": flow_result.get("reason", "")
            }

        # 生成报告
        report = await self._generate_report(flow_result.get("data", {}))

        return {
            "response": f"{problem_type} 问题分析完成。",
            "state": self.state_machine.state,
            "report": report.to_dict()
        }

    async def _handle_user_choice(
        self,
        intent,
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """处理用户选择"""
        choice = intent.choice

        # 清除待选择项
        self.current_session.context.pending_choices = None
        self.state_machine.transition(Event.INPUT_RECEIVED)

        # 继续执行分析流程
        flow_result = await self.tool_orchestrator.continue_with_choice(
            choice,
            self.state_machine.context
        )

        # 检查是否需要更多输入
        if flow_result.get("need_input"):
            return {
                "response": flow_result.get("question", "请选择："),
                "state": self.state_machine.state,
                "options": [opt.to_dict() for opt in flow_result.get("options", [])],
                "reason": flow_result.get("reason", "")
            }

        # 生成报告
        report = await self._generate_report(flow_result.get("data", {}))

        return {
            "response": f"已选择: {choice}，分析完成。",
            "state": self.state_machine.state,
            "report": report.to_dict()
        }

    async def _handle_continue(self) -> Dict[str, Any]:
        """处理继续请求"""
        # 恢复上次的分析
        last_results = self.current_session.context.analysis_results

        if not last_results:
            return {
                "response": "没有找到上次的分析记录，请重新开始分析。",
                "state": self.state_machine.state
            }

        # 继续执行
        self.state_machine.transition(Event.CONTINUE)

        return {
            "response": "继续上次的分析...",
            "state": self.state_machine.state,
            "data": last_results
        }

    async def _handle_feedback(self, intent) -> Dict[str, Any]:
        """处理反馈请求"""
        adopted = intent.adopted
        comment = intent.comment

        # 更新案例库
        if self.current_session.context.case_id:
            self.case_manager.update_feedback(
                self.current_session.context.case_id,
                adopted,
                comment
            )

        return {
            "response": f"感谢您的反馈！{'已采纳建议' if adopted else '已记录您的意见'}",
            "state": self.state_machine.state
        }

    async def _handle_question(self, message: str) -> Dict[str, Any]:
        """处理一般问题"""
        # 检索相关知识
        knowledge_context = await self._retrieve_knowledge(message)

        # 构建提示词
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(message, knowledge_context)

        # 调用LLM生成回答
        llm_response = await self.llm_router.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=4096
        )

        response_content = llm_response.get("content", "")

        # 添加Agent消息
        agent_msg = Message(
            id=str(uuid.uuid4()),
            role="agent",
            content=response_content,
            timestamp=datetime.now()
        )
        self.current_session.messages.append(agent_msg)

        return {
            "response": response_content,
            "state": self.state_machine.state
        }

    async def _retrieve_knowledge(self, query: str) -> List[Dict[str, Any]]:
        """检索相关知识"""
        if not self.knowledge_retriever:
            return []

        try:
            docs = self.knowledge_retriever.retrieve(query, top_k=3)
            return docs
        except Exception:
            return []

    async def _generate_report(self, analysis_data: Dict[str, Any]) -> AnalysisReport:
        """生成分析报告"""
        # 检索相似案例
        similar_cases = await self._retrieve_similar_cases(analysis_data)

        # 检索相关知识
        knowledge = await self._retrieve_knowledge(str(analysis_data))

        # 生成报告
        report = await self.report_generator.generate(
            analysis_data,
            similar_cases=similar_cases,
            knowledge_context=knowledge
        )

        # 保存到案例库
        case_id = self.case_manager.save_case({
            "session_id": self.current_session.id,
            "analysis_data": analysis_data,
            "report": report.to_dict()
        })
        self.current_session.context.case_id = case_id

        return report

    async def _retrieve_similar_cases(self, analysis_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检索相似案例"""
        if not self.case_manager:
            return []

        try:
            problem_desc = str(analysis_data.get("analysis_results", {}))
            cases = self.case_manager.find_similar_cases(problem_desc)
            return [{"id": c.id, "problem_description": c.problem_description} for c in cases]
        except Exception:
            return []

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return """你是一个AI性能分析助手，专门帮助用户分析和解决AI模型训练和推理过程中的性能问题。

你的职责：
1. 理解用户的性能分析需求
2. 调用MCP工具进行数据分析
3. 生成诊断报告和优化建议

分析流程：
1. 解析用户提供的profiling数据
2. 检测问题类型（通信、内存、计算等）
3. 选择合适的分析工具
4. 生成报告

当需要用户选择时（如选择通信域），请清晰地提供选项和解释原因。"""

    def _build_user_prompt(self, message: str, knowledge_context: List[Dict[str, Any]]) -> str:
        """构建用户提示词"""
        prompt = f"用户问题: {message}\n\n"

        if knowledge_context:
            prompt += "相关知识:\n"
            for doc in knowledge_context:
                prompt += f"- {doc.get('content', '')[:500]}\n"
            prompt += "\n"

        prompt += "请基于以上知识回答用户问题，如果需要分析数据，请告知用户提供数据路径。"

        return prompt

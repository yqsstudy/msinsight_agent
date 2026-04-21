"""工具编排器 - MCP工具编排执行"""

import asyncio
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime

from .state_machine import AnalysisStateMachine, Event, State
from ..mcp import MCPClient
from ..models import ToolCallRecord, Option


class ToolOrchestrator:
    """MCP工具编排执行"""

    # 分析流程定义
    ANALYSIS_FLOWS = {
        "full_analysis": [
            "parse_data",
            "get_overview",
            "detect_problem_type",
            "select_tools",       # 动态决策点
            "execute_analysis",
            "generate_report"
        ],
        "memory_analysis": [
            "parse_data",
            "analyze_memory",
            "generate_report"
        ],
        "communication_analysis": [
            "parse_data",
            "get_comm_domains",   # 可能需要用户选择
            "analyze_slow_cards",
            "generate_report"
        ]
    }

    # 工具依赖关系
    TOOL_DEPENDENCIES = {
        "get_overview": ["parse_data"],
        "get_comm_domains": ["parse_data"],
        "analyze_slow_cards": ["parse_data", "get_comm_domains"],
        "analyze_memory": ["parse_data"],
    }

    def __init__(self, mcp_client: MCPClient, state_machine: AnalysisStateMachine = None):
        self.mcp = mcp_client
        self.state_machine = state_machine or AnalysisStateMachine()
        self.tool_call_history: List[ToolCallRecord] = []
        self._pending_user_input: bool = False
        self._pending_options: List[Option] = []
        self._pending_reason: str = ""

    async def execute_flow(
        self,
        flow_name: str,
        params: Dict[str, Any],
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """
        执行分析流程

        Args:
            flow_name: 流程名称
            params: 参数（包含data_path等）
            on_need_input: 需要用户输入时的回调函数

        Returns:
            流程执行结果
        """
        if flow_name not in self.ANALYSIS_FLOWS:
            raise ValueError(f"Unknown flow: {flow_name}")

        flow_steps = self.ANALYSIS_FLOWS[flow_name]
        result = {"flow": flow_name, "steps": [], "data": {}}

        # 启动状态机
        self.state_machine.reset()
        self.state_machine.transition(Event.START)

        try:
            for step in flow_steps:
                step_result = await self._execute_step(
                    step, params, result["data"], on_need_input
                )
                result["steps"].append({
                    "step": step,
                    "success": step_result.get("success", True),
                    "data": step_result.get("data")
                })

                if step_result.get("need_input"):
                    result["need_input"] = True
                    result["question"] = step_result.get("question")
                    result["options"] = step_result.get("options")
                    result["reason"] = step_result.get("reason")
                    return result

                if not step_result.get("success", True):
                    result["error"] = step_result.get("error")
                    self.state_machine.transition(Event.ANALYZE_ERROR)
                    return result

                # 更新数据
                if step_result.get("data"):
                    result["data"].update(step_result["data"])

            # 完成
            self.state_machine.transition(Event.REPORT_SUCCESS)
            result["success"] = True

        except Exception as e:
            self.state_machine.transition(Event.ANALYZE_ERROR)
            result["error"] = str(e)
            result["success"] = False

        return result

    async def _execute_step(
        self,
        step: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """执行单个步骤"""

        # 动态决策步骤
        if step == "select_tools":
            return await self._select_tools(context)
        elif step == "execute_analysis":
            return await self._execute_analysis(context, params, on_need_input)
        elif step == "generate_report":
            return {"success": True, "data": {"report_ready": True}}
        elif step == "detect_problem_type":
            return await self._detect_problem_type(context)

        # MCP工具调用
        return await self._call_mcp_tool(step, context, params)

    async def _call_mcp_tool(
        self,
        tool_name: str,
        context: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用MCP工具"""

        # 构建工具参数
        tool_params = self._build_tool_params(tool_name, context, params)

        # 记录调用
        record = ToolCallRecord(
            tool_name=tool_name,
            input_params=tool_params,
            output={},
            timestamp=datetime.now()
        )

        try:
            result = await self.mcp.call_tool(tool_name, tool_params)
            record.output = result
            record.success = True
            self.tool_call_history.append(record)
            return {"success": True, "data": result}

        except Exception as e:
            record.success = False
            record.error_message = str(e)
            self.tool_call_history.append(record)
            return {"success": False, "error": str(e)}

    def _build_tool_params(
        self,
        tool_name: str,
        context: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """构建工具参数"""
        tool_params = {}

        if tool_name == "parse_data":
            tool_params["data_path"] = params.get("data_path")
        elif tool_name in ["get_overview", "get_comm_domains", "analyze_memory"]:
            tool_params["data_id"] = context.get("data_id")
        elif tool_name == "analyze_slow_cards":
            tool_params["data_id"] = context.get("data_id")
            tool_params["domain"] = params.get("domain") or context.get("selected_domain")

        return tool_params

    async def _select_tools(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """根据检测结果选择工具"""
        problem_types = context.get("problem_types", [])
        selected_tools = []

        if "communication" in problem_types:
            selected_tools.append("communication_analysis")
        if "memory" in problem_types:
            selected_tools.append("memory_analysis")

        return {"success": True, "data": {"selected_tools": selected_tools}}

    async def _detect_problem_type(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """检测问题类型"""
        overview = context.get("overview", {})
        problem_types = overview.get("problem_types", ["communication", "memory"])
        return {"success": True, "data": {"problem_types": problem_types}}

    async def _execute_analysis(
        self,
        context: Dict[str, Any],
        params: Dict[str, Any],
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """执行分析（处理用户交互）"""
        selected_tools = context.get("selected_tools", [])
        analysis_results = {}

        for tool in selected_tools:
            if tool == "communication_analysis":
                result = await self._analyze_communication(context, params, on_need_input)
                if result.get("need_input"):
                    return result
                analysis_results["communication"] = result.get("data")

            elif tool == "memory_analysis":
                result = await self._call_mcp_tool("analyze_memory", context, params)
                if result["success"]:
                    analysis_results["memory"] = result["data"]

        return {"success": True, "data": {"analysis_results": analysis_results}}

    async def _analyze_communication(
        self,
        context: Dict[str, Any],
        params: Dict[str, Any],
        on_need_input: Callable = None
    ) -> Dict[str, Any]:
        """通信分析（可能需要用户选择通信域）"""
        # 获取通信域列表
        result = await self._call_mcp_tool("get_comm_domains", context, params)
        if not result["success"]:
            return result

        domains = result["data"].get("domains", [])

        # 如果有多个通信域，需要用户选择
        if len(domains) > 1 and not params.get("domain"):
            options = [
                Option(
                    value=d.get("name"),
                    label=d.get("name"),
                    description=f"包含 {d.get('rank_count', '?')} 个rank"
                )
                for d in domains
            ]
            reason = "检测到多个通信域，请选择要分析的通信域。建议先分析world_group获取全局视图。"

            if on_need_input:
                await on_need_input("请选择通信域", options, reason)

            return {
                "need_input": True,
                "question": "请选择要分析的通信域",
                "options": options,
                "reason": reason,
                "data": {"domains": domains}
            }

        # 单个通信域或已选择
        domain = params.get("domain") or (domains[0].get("name") if domains else None)
        if domain:
            params["domain"] = domain
            return await self._call_mcp_tool("analyze_slow_cards", context, params)

        return {"success": False, "error": "No communication domain available"}

    async def continue_with_choice(self, choice: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """用户选择后继续执行"""
        context["selected_domain"] = choice
        return await self._call_mcp_tool(
            "analyze_slow_cards",
            context,
            {"domain": choice}
        )

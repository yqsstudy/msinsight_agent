"""报告生成器 - 生成诊断报告"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid

from ..models.evidence import Evidence, EvidenceType

from ..models import (
    AnalysisReport, Problem, Diagnosis, Suggestion,
    ToolCallRecord, DataInfo, KnowledgeRef, CaseRef
)
from ..knowledge import KnowledgeRetriever
from ..case_lib import CaseLibManager


class ReportGenerator:
    """生成诊断报告"""

    def __init__(
        self,
        knowledge_retriever: KnowledgeRetriever = None,
        case_manager: CaseLibManager = None
    ):
        self.knowledge_retriever = knowledge_retriever
        self.case_manager = case_manager

    async def generate(
        self,
        analysis_data: Dict[str, Any],
        similar_cases: List[Dict[str, Any]] = None,
        knowledge_context: List[Dict[str, Any]] = None,
        tool_history: List[ToolCallRecord] = None
    ) -> AnalysisReport:
        """
        生成分析报告

        Args:
            analysis_data: 分析数据
            similar_cases: 相似案例
            knowledge_context: 知识上下文
            tool_history: 工具调用历史

        Returns:
            AnalysisReport: 分析报告
        """
        report = AnalysisReport(
            id=str(uuid.uuid4()),
            session_id=analysis_data.get("session_id", "")
        )

        # 设置数据信息
        if analysis_data.get("data_id"):
            report.data_info = DataInfo(
                data_id=analysis_data["data_id"],
                data_type=analysis_data.get("data_type", "unknown"),
                file_path=analysis_data.get("data_path", ""),
                summary=analysis_data.get("summary", {})
            )

        # 提取问题
        report.problems = self._extract_problems(analysis_data)

        # 生成诊断
        report.diagnosis = self._generate_diagnosis(analysis_data, tool_history)

        # 生成建议
        report.suggestions = self._generate_suggestions(analysis_data, report.problems)

        # 添加知识引用
        if knowledge_context:
            report.knowledge_refs = [
                KnowledgeRef(
                    doc_id=k.get("doc_id", ""),
                    chunk_id=k.get("chunk_id", ""),
                    content=k.get("content", ""),
                    relevance_score=k.get("score", 0.0)
                )
                for k in knowledge_context
            ]

        # 添加相似案例引用
        if similar_cases:
            report.similar_cases = [
                CaseRef(
                    case_id=c.get("id", c.get("case_id", "")),
                    problem_description=c.get("problem_description", ""),
                    similarity_score=c.get("similarity_score", c.get("score", 0.0))
                )
                for c in similar_cases
            ]

        return report

    def generate_markdown_from_evidence(
        self,
        session_id: str,
        user_goal: str,
        evidence: List[Evidence],
    ) -> str:
        """基于 Evidence 生成可审计 Markdown 报告。"""
        rag_items = [item for item in evidence if item.type == EvidenceType.RAG_EVIDENCE]
        mcp_items = [item for item in evidence if item.type == EvidenceType.MCP_OBSERVATION]
        user_items = [item for item in evidence if item.type == EvidenceType.USER_INPUT]
        conclusions = [item for item in evidence if item.type == EvidenceType.AGENT_CONCLUSION]
        system_events = [item for item in evidence if item.type == EvidenceType.SYSTEM_EVENT]

        lines = [
            "# 性能诊断报告",
            "",
            "## 1. 问题摘要",
            "",
            user_goal or "本次会话未记录明确问题摘要。",
            "",
            f"- 会话 ID：`{session_id}`",
            f"- 生成时间：{datetime.utcnow().isoformat()}",
            "",
            "## 2. 当前结论",
            "",
        ]

        if conclusions:
            lines.extend([f"- [{item.id}] {item.summary or item.content}" for item in conclusions])
        elif mcp_items:
            lines.append("- 已完成部分 MCP 实测分析，具体结论需结合下方证据继续判断。")
        elif rag_items:
            lines.append("- 当前仅包含 RAG 知识依据，尚未获得 MCP 实测 profiling 数据。")
        else:
            lines.append("- 当前证据不足，无法形成可靠结论。")

        lines.extend(["", "## 3. 证据链", "", "### 3.1 MCP 实测证据", ""])
        if mcp_items:
            for item in mcp_items:
                tool = item.metadata.get("internal_tool") or item.metadata.get("mcp_tool") or item.source
                lines.extend([
                    f"- **{tool}** (`{item.id}`)",
                    f"  - 摘要：{item.summary or item.content[:300]}",
                ])
        else:
            lines.append("- 暂无 MCP 实测证据。")

        lines.extend(["", "### 3.2 RAG 知识依据", ""])
        if rag_items:
            for item in rag_items:
                title = item.metadata.get("title") or item.metadata.get("path") or item.source
                lines.extend([
                    f"- **{title}** (`{item.id}`)",
                    f"  - 摘要：{item.summary or item.content[:300]}",
                ])
        else:
            lines.append("- 暂无 RAG 知识依据。")

        lines.extend(["", "## 4. 可能根因排序", ""])
        if mcp_items:
            lines.append("1. `inference`：需要根据 MCP observation 中的异常指标进一步确认根因。")
        else:
            lines.append("1. `unknown`：缺少实测数据，暂不排序根因。")

        lines.extend(["", "## 5. 建议下一步操作", ""])
        if mcp_items:
            lines.append("- 继续按照 MCP 返回的下一步 playbook 执行，直到剧本完成或出现需要人工选择的分支。")
        else:
            lines.append("- 提供 profiling 文件路径并启动 MCP 服务后，执行实测分析。")
        if rag_items:
            lines.append("- 结合 RAG 知识依据中的定位流程检查相关指标。")

        lines.extend(["", "## 6. 风险与不确定性", ""])
        if system_events:
            for item in system_events:
                lines.append(f"- [{item.id}] {item.summary or item.content}")
        else:
            lines.append("- 当前报告由已收集 evidence 自动生成，未覆盖的工具步骤可能改变最终判断。")

        lines.extend(["", "## 7. 引用来源", ""])
        for item in evidence:
            lines.append(f"- `{item.id}`：{item.type.value} / {item.source}")

        if user_items:
            lines.extend(["", "## 附录：用户输入", ""])
            for item in user_items:
                lines.append(f"- `{item.id}`：{item.content}")

        return "\n".join(lines)

    def _extract_problems(self, analysis_data: Dict[str, Any]) -> List[Problem]:
        """从分析数据中提取问题"""
        problems = []
        analysis_results = analysis_data.get("analysis_results", {})

        # 通信问题
        comm_result = analysis_results.get("communication", {})
        if comm_result.get("slow_cards"):
            for card in comm_result["slow_cards"]:
                problems.append(Problem(
                    type="communication",
                    severity="high" if card.get("severity") == "high" else "medium",
                    description=f"慢卡检测: Rank {card.get('rank')} 通信延迟较高",
                    location=f"Rank {card.get('rank')}"
                ))

        # 内存问题
        mem_result = analysis_results.get("memory", {})
        if mem_result.get("issues"):
            for issue in mem_result["issues"]:
                problems.append(Problem(
                    type="memory",
                    severity=issue.get("severity", "medium"),
                    description=issue.get("description", "内存问题"),
                    location=issue.get("location", "unknown")
                ))

        return problems

    def _generate_diagnosis(
        self,
        analysis_data: Dict[str, Any],
        tool_history: List[ToolCallRecord] = None
    ) -> Diagnosis:
        """生成诊断结果"""
        analysis_results = analysis_data.get("analysis_results", {})

        # 分析根因
        root_cause = self._analyze_root_cause(analysis_results)

        # 收集证据
        evidence = self._collect_evidence(analysis_results)

        return Diagnosis(
            root_cause=root_cause,
            evidence=evidence,
            analysis_process=tool_history or []
        )

    def _analyze_root_cause(self, analysis_results: Dict[str, Any]) -> str:
        """分析根因"""
        causes = []

        comm_result = analysis_results.get("communication", {})
        if comm_result.get("slow_cards"):
            slow_count = len(comm_result["slow_cards"])
            causes.append(f"检测到 {slow_count} 个慢卡，可能存在通信瓶颈")

        mem_result = analysis_results.get("memory", {})
        if mem_result.get("issues"):
            causes.append("检测到内存相关问题")

        if causes:
            return "；".join(causes)
        return "未检测到明显性能问题"

    def _collect_evidence(self, analysis_results: Dict[str, Any]) -> List[str]:
        """收集证据"""
        evidence = []

        comm_result = analysis_results.get("communication", {})
        if comm_result.get("metrics"):
            evidence.append(f"通信指标: {comm_result['metrics']}")

        mem_result = analysis_results.get("memory", {})
        if mem_result.get("metrics"):
            evidence.append(f"内存指标: {mem_result['metrics']}")

        return evidence

    def _generate_suggestions(
        self,
        analysis_data: Dict[str, Any],
        problems: List[Problem]
    ) -> List[Suggestion]:
        """生成优化建议"""
        suggestions = []

        # 基于问题类型生成建议
        problem_types = set(p.type for p in problems)

        if "communication" in problem_types:
            suggestions.append(Suggestion(
                description="检查网络拓扑和通信模式",
                priority=1,
                expected_improvement="减少通信延迟",
                action_items=[
                    "检查是否存在跨节点通信",
                    "优化通信域划分",
                    "考虑使用通信优化技术（如通信重叠）"
                ],
                knowledge_source="knowledge_base"
            ))

        if "memory" in problem_types:
            suggestions.append(Suggestion(
                description="优化内存使用",
                priority=1,
                expected_improvement="减少内存压力",
                action_items=[
                    "检查是否存在内存泄漏",
                    "优化模型并行策略",
                    "调整batch size"
                ],
                knowledge_source="knowledge_base"
            ))

        return suggestions

    def _retrieve_knowledge(
        self,
        analysis_data: Dict[str, Any],
        problems: List[Problem]
    ) -> List[KnowledgeRef]:
        """检索知识库"""
        refs = []
        for problem in problems:
            chunks = self.knowledge_retriever.retrieve(
                query=problem.description,
                problem_type=problem.type,
                top_k=2
            )
            for chunk in chunks:
                refs.append(KnowledgeRef(
                    doc_id=chunk.get("doc_id", ""),
                    chunk_id=chunk.get("chunk_id", ""),
                    content=chunk.get("content", ""),
                    relevance_score=chunk.get("score", 0.0)
                ))
        return refs

    def _find_similar_cases(self, analysis_data: Dict[str, Any]) -> List[CaseRef]:
        """查找相似案例"""
        problem_desc = self._build_problem_description(analysis_data)
        cases = self.case_manager.find_similar_cases(problem_desc, top_k=3)

        return [
            CaseRef(
                case_id=c.id,
                problem_description=c.problem_description,
                similarity_score=getattr(c, "similarity_score", getattr(c, "score", 0.0))
            )
            for c in cases
        ]

    def _build_problem_description(self, analysis_data: Dict[str, Any]) -> str:
        """构建问题描述用于案例匹配"""
        parts = []
        analysis_results = analysis_data.get("analysis_results", {})

        if analysis_results.get("communication"):
            parts.append("通信问题")
        if analysis_results.get("memory"):
            parts.append("内存问题")

        return "、".join(parts) if parts else "性能分析"

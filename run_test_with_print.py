import asyncio
from unittest.mock import AsyncMock, MagicMock
import sys
sys.path.append('/Users/ye/yangqisheng/msinsight_agent/agent-service')

from src.core.agents.diagnosis_agent import DiagnosisAgent
from src.models.orchestration import MCPNextStep, MCPToolResult

async def run():
    mock_gateway = AsyncMock()
    mock_next_step = MCPNextStep(tool_name="next_tool", schema={"properties": {"param1": {"type": "string"}}, "required": ["param1"]})
    mock_result = MCPToolResult(status="success", text="ok", next_step=mock_next_step)
    mock_gateway.execute_profiler_tool.return_value = mock_result
    
    mock_policy = MagicMock()
    mock_policy_decision = MagicMock()
    mock_policy_decision.action = "continue_auto"
    mock_policy.decide_after_mcp_result.return_value = mock_policy_decision
    
    mock_llm = AsyncMock()
    mock_llm.extract_parameters.return_value = {} # simulates missing param
    
    agent = DiagnosisAgent(mock_gateway, MagicMock(), mock_policy, mock_llm)
    
    result = await agent._execute_tool_and_check_next("ses1", "step1", "tool1", {}, 0, {})
    print(f"Status: {result.status}, Error: {result.error_msg}")

asyncio.run(run())

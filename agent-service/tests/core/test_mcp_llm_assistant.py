import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.mcp_llm_assistant import MCPLLMOrchestrationAssistant
from src.models.orchestration import LLMParameterExtractionResult

@pytest.mark.asyncio
async def test_extract_parameters_by_schema():
    mock_router = MagicMock()
    mock_router.chat = AsyncMock()
    # Mock LLM returning JSON matching the schema
    mock_router.chat.return_value = '{"iterationId": "5"}'
    
    assistant = MCPLLMOrchestrationAssistant(mock_router, MagicMock())
    
    schema = {
        "properties": {"iterationId": {"type": "string"}},
        "required": ["iterationId"]
    }
    
    result = await assistant.extract_parameters_by_schema(
        user_input="帮我查一下第五个迭代",
        tool_schema=schema,
        existing_args={"clusterPath": "/data"}
    )
    
    assert result == {"iterationId": "5"}
    mock_router.chat.assert_called_once()
    call_args = mock_router.chat.call_args[0][0]
    assert "帮我查一下第五个迭代" in str(call_args)
    assert "iterationId" in str(call_args)

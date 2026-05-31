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
    
    assistant = MCPLLMOrchestrationAssistant(mock_router)
    
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
    call_kwargs = mock_router.chat.call_args.kwargs
    messages = call_kwargs.get("messages", [])
    assert "帮我查一下第五个迭代" in str(messages)
    assert "iterationId" in str(messages)

@pytest.mark.asyncio
async def test_extract_parameters_by_schema_invalid_json():
    mock_router = MagicMock()
    mock_router.chat = AsyncMock()
    # Mock LLM returning invalid JSON string
    mock_router.chat.return_value = 'I cannot help with that'
    
    # Use default config so timeout_seconds is a real number
    assistant = MCPLLMOrchestrationAssistant(mock_router)
    
    schema = {
        "properties": {"iterationId": {"type": "string"}}
    }
    
    result = await assistant.extract_parameters_by_schema(
        user_input="hello there",
        tool_schema=schema,
        existing_args={}
    )
    
    assert result == {}
    mock_router.chat.assert_called_once()


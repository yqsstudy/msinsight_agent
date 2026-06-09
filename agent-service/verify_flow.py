import asyncio
import json
from src.core.orchestrator import Orchestrator

async def verify_multi_agent_flow():
    print("🚀 Initializing Orchestrator (Multi-turn E2E Test)...")
    orchestrator = Orchestrator()
    session_id = "test_verify_session_multi_turn"
    
    # 1. Initial request
    message = "帮我分析一下 profiling 性能"
    print(f"\n[User]: {message}")
    
    print("--- SSE Events (Turn 1: Initial) ---")
    async for envelope in orchestrator.handle_message(session_id, message):
        event_type = envelope.event
        print(f"Event: {event_type}")
        if event_type == "user_input_required":
            data = envelope.data
            print(f"💡 ACTION REQUIRED: {data.get('question')}")
            # If it's a choice, show options
            if data.get("input_type") == "choice":
                print(f"Options: {[o.get('value') for o in data.get('options', [])]}")

    # 2. Resumption 1: Select Playbook
    # Based on the real MCP output, we should select 'fast_slow_rank'
    playbook_choice = "fast_slow_rank"
    print(f"\n[User Choice]: {playbook_choice}")
    
    print("\n--- SSE Events (Turn 2: Resumption - Playbook Selected) ---")
    async for envelope in orchestrator.continue_with_input(session_id, playbook_choice):
        event_type = envelope.event
        print(f"Event: {event_type}")
        if event_type == "user_input_required":
            data = envelope.data
            print(f"💡 ACTION REQUIRED: {data.get('question')}")
            
    # 3. Resumption 2: Provide Path
    # Now it should ask for the path because we selected a playbook that requires one
    mock_path = "/Users/ye/yangqisheng/msinsight_agent/tests/data/sample_prof"
    print(f"\n[User Path]: {mock_path}")
    
    print("\n--- SSE Events (Turn 3: Resumption - Path Provided) ---")
    async for envelope in orchestrator.continue_with_input(session_id, mock_path):
        event_type = envelope.event
        data = envelope.data
        print(f"Event: {event_type}")
        if event_type == "user_input_required":
            print(f"💡 ACTION REQUIRED: {data.get('question')}")

    # 4. Resumption 3: Provide Iteration ID
    # After the trace is imported and the iterations are fetched, it should ask for iterationId
    iteration_id = "1"
    print(f"\n[User Iteration ID]: {iteration_id}")
    
    print("\n--- SSE Events (Turn 4: Resumption - Iteration ID Provided) ---")
    async for envelope in orchestrator.continue_with_input(session_id, iteration_id):
        event_type = envelope.event
        data = envelope.data
        if event_type == "analysis_result":
            print(f"✅ RESULT: {data.get('summary')}")
        if event_type == "message_end":
            print(f"🏁 STATE: {data.get('state')}")

if __name__ == "__main__":
    asyncio.run(verify_multi_agent_flow())

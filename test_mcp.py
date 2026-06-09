import asyncio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    server_params = StdioServerParameters(
        command="python3",
        args=["main.py"],
        env={"MSINSIGHT_MCP_TRANSPORT": "stdio", "MSINSIGHT_LOG_LEVEL": "DEBUG"},
        cwd="/Users/ye/yangqisheng/msinsight_agent/mcp_service_code/ms_mcp"
    )

    print("Starting client...")
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("Initialized. Calling tool...")
                result = await session.call_tool(
                    "search_profiler_tools", 
                    {"query": "帮我看看存在快慢卡问题", "select_playbook": "fast_slow_rank"}
                )
                print("Result:", result)
    except Exception as e:
        print("Caught exception:", type(e).__name__, e)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from fastmcp import Client


async def test_server():
  # Test the MCP server using http transport.
  async with Client("http://localhost:8000/mcp") as client:
    # List available tools
    tools = await client.list_tools()
    for tool in tools:
      print(f">>> Tool found: {tool.name}")
    # Call memory_trend tool
    print(">>> Calling memory_trend tool")
    result = await client.call_tool("memory_trend")
    print(f"<<< Result: {result}")


if __name__ == "__main__":
  asyncio.run(test_server())

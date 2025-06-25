import asyncio
from fastmcp import Client

# Instantiate the client with the path to the server script
client = Client("mcp_server.py")

async def async_trigger_processing(reg_no: str, filenames: list):
    # Calls the 'process_upload' tool on the MCP server
    async with client:
        result = await client.call_tool("process_upload", {"reg_no": reg_no, "filenames": filenames})
        return result

def trigger_processing(reg_no: str, filenames: list):
    # Synchronous wrapper for compatibility
    return asyncio.run(async_trigger_processing(reg_no, filenames)) 
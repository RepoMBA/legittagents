import asyncio
from fastmcp import Client

# Instantiate the client with the path to the server script
# client = Client("/home/ubuntu/proj/legittagents/ACI/mcp_server.py")

async def async_trigger_processing(reg_no: str, filenames: list):
    # Calls the 'process_upload' tool on the MCP server
    if not filenames:
        raise ValueError("No filenames provided for processing.")

    if not reg_no:
        raise ValueError("Registration number (reg_no) must be provided.")
    if not isinstance(filenames, list):
        raise ValueError("Filenames must be provided as a list.")

    if not all(isinstance(filename, str) for filename in filenames):
        raise ValueError("All filenames must be strings.")
    
    from file_mover import move_multiple_files, process_pdf_folder
    rbresult = process_upload(reg_no, filenames)
    return rbresult
    # async with client:
    #     result = await client.call_tool("process_upload", {"reg_no": reg_no, "filenames": filenames})
    #     return result

def trigger_processing(reg_no: str, filenames: list):
    # Synchronous wrapper for compatibility
    return asyncio.run(async_trigger_processing(reg_no, filenames))

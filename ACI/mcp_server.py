from fastmcp import FastMCP
from file_mover import move_multiple_files, process_pdf_folder
from datetime import datetime

mcp = FastMCP("MCPxlsxGen Server")

@mcp.tool()
def process_upload(reg_no: str, filenames: list, log_callback=None):
    """Move files for a registration number and process the folder, streaming logs if log_callback is provided."""
    today_str = datetime.today().strftime("%Y%m%d%H%M%S")
    move_multiple_files([reg_no], today_str, log_callback=log_callback)
    result_path, excel_path = process_pdf_folder(today_str, log_callback=log_callback)
    return {"status": "success", "processed_folder": str(result_path), "excel_file": str(excel_path)}

if __name__ == "__main__":
    mcp.run() 
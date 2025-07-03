from fastmcp import FastMCP #type: ignore
from pathlib import Path
from file_mover import move_multiple_files, process_pdf_folder, DATABASE_PATH, TODAY_STR
from datetime import datetime

mcp = FastMCP("ACI Server")

@mcp.tool()
def process_upload(reg_no: str, filenames: list, log_callback=None):
    """Move files for a registration number and process the folder, streaming logs if log_callback is provided."""
    move_multiple_files([reg_no], TODAY_STR, log_callback=log_callback)
    result_path, excel_path = process_pdf_folder(TODAY_STR, log_callback=log_callback)

    # Convert absolute paths to relative (under Database/) so the frontend can
    # fetch them via /static/{path}
    rel_folder = str(Path(result_path).relative_to(DATABASE_PATH))
    rel_excel  = str(Path(excel_path).relative_to(DATABASE_PATH))

    return {
        "status": "success",
        "processed_folder": rel_folder,
        "excel_file": rel_excel,
    }

if __name__ == "__main__":
    mcp.run() 
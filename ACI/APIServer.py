import shutil
from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
import os
import uvicorn
from typing import List, Dict
from mcp_client import async_trigger_processing
import asyncio
import aiofiles
import time
import glob
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
PROJECT_PATH = "./ACI"
DATABASE_PATH = "./ACI/Database"
app.mount("/ACI/Database/Processed", StaticFiles(directory=f"{DATABASE_PATH}/Processed"), name="processed")
app.mount("/ACI/Database/Processing", StaticFiles(directory=f"{DATABASE_PATH}/Processing"), name="processing")
app.mount("/ACI/static", StaticFiles(directory="./ACI/static"), name="static")

UPLOAD_DIRECTORY = f"{DATABASE_PATH}/To_Be_Processed"

if not os.path.exists(UPLOAD_DIRECTORY):
    os.makedirs(UPLOAD_DIRECTORY)

# --- Log manager for WebSocket connections ---
active_websockets: Dict[str, WebSocket] = {}

async def send_log_to_ws(reg_no: str, message: str):
    websocket = active_websockets.get(reg_no)
    if websocket:
        try:
            await websocket.send_text(message)
        except Exception:
            pass  # Ignore errors if client disconnected

@app.websocket("/ws/logs/{reg_no}")
async def websocket_endpoint(websocket: WebSocket, reg_no: str):
    await websocket.accept()
    log_dir = f"{DATABASE_PATH}/To_Be_Processed/move_logs/"
    # Find the latest log file
    log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), reverse=True)
    if not log_files:
        await websocket.send_text("No log file found yet. This is normal for the first upload of the day.\n")
        await websocket.close()
        return
    log_file_path = log_files[0]  # Use the latest log file
    try:
        async with aiofiles.open(log_file_path, "r") as log_file:
            await log_file.seek(0, os.SEEK_END)
            while True:
                line = await log_file.readline()
                if line:
                    await websocket.send_text(line)
                else:
                    await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass

@app.post("/uploadfile/")
async def create_upload_files(reg_no: str = Form(...), files: List[UploadFile] = File(...)):
    upload_dir = os.path.join(UPLOAD_DIRECTORY, reg_no)
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    saved_files = []
    for file in files:
        if file.filename:
            file_location = os.path.join(upload_dir, file.filename)
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(file.file, file_object)
            saved_files.append(file.filename)
    # Trigger MCP processing
    processing_result = await async_trigger_processing(reg_no, saved_files)
    excel_file_path = None
    if isinstance(processing_result, dict):
        excel_file_path = processing_result.get("excel_file")
        processed_folder = processing_result.get("processed_folder")
    elif isinstance(processing_result, list) and processing_result and isinstance(processing_result[0], dict):
        excel_file_path = processing_result[0].get("excel_file")
        processed_folder = processing_result[0].get("processed_folder")
    else:
        processed_folder = None

    # Read move log (latest by date)
    import glob
    import datetime
    log_dir = f"{DATABASE_PATH}/To_Be_Processed/move_logs/"
    log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), reverse=True)
    move_log_content = ""
    if log_files:
        try:
            with open(log_files[0], "r") as f:
                move_log_content = f.read()
        except (FileNotFoundError, IOError) as e:
            # Handle case where log file doesn't exist or can't be read
            move_log_content = f"Note: Move log not available yet (first upload of the day)\n"
    else:
        # No log files exist yet (first upload of the day)
        move_log_content = "Note: Move log not available yet (first upload of the day)\n"

    # Read processing log (from processed folder)
    processing_log_content = ""
    if processed_folder:
        processing_log_path = os.path.join(processed_folder, "processing_log.log")
        if os.path.exists(processing_log_path):
            with open(processing_log_path, "r") as f:
                processing_log_content = f.read()

    if excel_file_path and os.path.exists(excel_file_path):
        return {
            "move_log": move_log_content,
            "processing_log": processing_log_content,
            "excel_file": excel_file_path,
            "info": f"files {saved_files} saved in {reg_no}",
            "processing_result": processing_result
        }
    return {
        "move_log": move_log_content,
        "processing_log": processing_log_content,
        "info": f"files {saved_files} saved in {reg_no}",
        "processing_result": processing_result
    }

@app.get("/download/move_log")
def download_latest_move_log():
    import glob
    import os
    log_dir = f"{DATABASE_PATH}/To_Be_Processed/move_logs/"
    log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), reverse=True)
    if not log_files:
        return {"error": "No move log file found yet. This is normal for the first upload of the day."}
    latest_log = log_files[0]
    return FileResponse(latest_log, filename=os.path.basename(latest_log), media_type='text/plain')

@app.get("/download/processing_log")
def download_processing_log(folder: str = ""):
    import glob
    import os
    processed_dir = f"{DATABASE_PATH}/Processed/"
    if folder:
        log_path = os.path.join(processed_dir, folder, "processing_log.log")
        if not os.path.exists(log_path):
            return {"error": f"No processing_log.log found in {folder}."}
        return FileResponse(log_path, filename=f"processing_log_{folder}.log", media_type='text/plain')
    # If no folder specified, get the latest processed folder
    folders = sorted([f for f in os.listdir(processed_dir) if os.path.isdir(os.path.join(processed_dir, f))], reverse=True)
    for f in folders:
        log_path = os.path.join(processed_dir, f, "processing_log.log")
        if os.path.exists(log_path):
            return FileResponse(log_path, filename=f"processing_log_{f}.log", media_type='text/plain')
    return {"error": "No processing_log.log found in any processed folder."}

@app.get("/download/excel")
def download_excel(folder: str = ""):
    import os
    processed_dir = f"{DATABASE_PATH}/Processed/"
    if folder:
        excel_path = os.path.join(processed_dir, folder, "combined_data.xlsx")
        if not os.path.exists(excel_path):
            return {"error": f"No combined_data.xlsx found in {folder}."}
        return FileResponse(excel_path, filename=f"combined_data_{folder}.xlsx", media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    # If no folder specified, get the latest processed folder
    folders = sorted([f for f in os.listdir(processed_dir) if os.path.isdir(os.path.join(processed_dir, f))], reverse=True)
    for f in folders:
        excel_path = os.path.join(processed_dir, f, "combined_data.xlsx")
        if os.path.exists(excel_path):
            return FileResponse(excel_path, filename=f"combined_data_{f}.xlsx", media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return {"error": "No combined_data.xlsx found in any processed folder."}

@app.get("/favicon.ico")
def favicon():
    return FileResponse(f"{PROJECT_PATH}/static/favicon.ico")

@app.get("/")
def serve_frontend():
    return FileResponse(f"{PROJECT_PATH}/frontend.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

    

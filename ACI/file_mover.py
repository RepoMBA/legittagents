import shutil
from pathlib import Path
from datetime import datetime
import pandas as pd
from Helper.extract_pdf_to_excel import data_retriever as extract_data_from_pdf
from config import DATABASE_DIRECTORY

# Constants for base directories
DATABASE_DIR = Path(DATABASE_DIRECTORY)
TO_BE_PROCESSED = DATABASE_DIR / "To_Be_Processed"
PROCESSING = DATABASE_DIR / "Processing"
PROCESSED = DATABASE_DIR / "Processed"
LOG_FOLDER = TO_BE_PROCESSED / "move_logs" 

def init_directories():
    PROCESSING.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)

init_directories()


def get_today_folder(today_str: str) -> Path:
    """Returns the processing folder path for the given date string, creating it if necessary."""
    today_folder = PROCESSING / today_str
    today_folder.mkdir(parents=True, exist_ok=True)
    return today_folder

def log_move(filename: str, reg_no: str, log_callback=None):
    """Appends a log entry about a moved file and optionally streams it."""
    log_dir = LOG_FOLDER
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    today_str = now.strftime("%Y%m%d")  # Only the date part for log file name
    date_str = now.strftime("%d/%m/%y %H:%M:%S")
    log_file = LOG_FOLDER / f"{today_str}.log"  # Log file named as today's date
    log_message = f"{filename} from folder {reg_no} moved to processing folder {today_str} on date {date_str}\n"
    with log_file.open("a") as log:
        log.write(log_message)
    if log_callback:
        log_callback(log_message)

def move_file(reg_no: str, today_str: str, log_callback=None):
    """
    Moves all files from to_be_processed/[REG_NO]/ to processing/[TODAY'S_DATE]/
    and logs the move. Deletes the source folder after moving.
    Creates a mapping file to remember original reg_no for each file.
    """
    src_folder = TO_BE_PROCESSED / reg_no
    if not src_folder.exists():
        raise FileNotFoundError(f"{src_folder} does not exist.")

    dest_folder = get_today_folder(today_str)
    files_moved = []
    
    # Create/update mapping file to store original reg_no for each file
    mapping_file = dest_folder / "file_reg_mapping.txt"
    
    for src_file in src_folder.iterdir():
        if src_file.is_file():
            shutil.copy2(str(src_file), str(dest_folder / src_file.name))
            log_move(src_file.name, reg_no, log_callback=log_callback)
            files_moved.append(src_file.name)
            
            # Store mapping of filename to original reg_no
            with mapping_file.open("a") as mapping:
                mapping.write(f"{src_file.name}:{reg_no}\n")
    
    # Delete the source folder after moving all files
    try:
        shutil.rmtree(src_folder)
        msg = f"Moved files {files_moved} from {reg_no} to {dest_folder} and deleted source folder."
    except Exception as e:
        msg = f"Moved files {files_moved} from {reg_no} to {dest_folder}. Warning: Could not delete source folder - {e}"
    
    print(msg)
    if log_callback:
        log_callback(msg + "\n")

def move_multiple_files(reg_no_list, today_str: str, log_callback=None):
    """
    Moves all files from each reg_no folder in the list.
    reg_no_list: List of registration numbers (folder names)
    """
    for reg_no in reg_no_list:
        try:
            move_file(reg_no, today_str, log_callback=log_callback)
        except Exception as e:
            err_msg = f"Error moving files from {reg_no}: {e}"
            print(err_msg)
            if log_callback:
                log_callback(err_msg + "\n")


def process_pdf_folder(date_folder: str, log_callback=None):
    """
    Processes all PDFs in the specified date folder (format: DD-MM-YY),
    saves a single Excel file, appends to local log, and moves the folder.
    Returns a tuple: (destination folder path, excel file path)
    """
    folder_path = PROCESSING / date_folder
    if not folder_path.exists():
        raise FileNotFoundError(f"No such processing folder: {folder_path}")

    pdf_files = list(folder_path.glob("*.pdf"))
    if not pdf_files:
        raise ValueError("No PDF files found in folder")

    # Extract data
    extracted_data = []
    success_files = []
    failed_files = []
    now = datetime.now()
    date_str = now.strftime("%d/%m/%y %H:%M:%S")
    local_log = folder_path / "processing_log.log"
    with local_log.open("a") as log:
        log.write(f"Started processing at {date_str}\n")
        for pdf_file in pdf_files:
            try:
                # Get original reg_no for this file
                original_reg_no = get_original_reg_no(folder_path, pdf_file.name)
                
                data = extract_data_from_pdf(pdf_file)
                
                # Override EnquiryNo with original reg_no if available
                if original_reg_no:
                    data['EnquiryNo'] = original_reg_no
                
                extracted_data.append(data)
                success_files.append(pdf_file.name)
                log.write(f"Processed: {pdf_file.name} (EnquiryNo: {original_reg_no})\n")
                if log_callback:
                    log_callback(f"Processed: {pdf_file.name} (EnquiryNo: {original_reg_no})\n")
            except Exception as e:
                err_msg = f"Error reading {pdf_file.name}: {e}\n"
                failed_files.append(pdf_file.name)
                print(err_msg)
                log.write(err_msg)
                if log_callback:
                    log_callback(err_msg)

    # Write to Excel
    df = pd.DataFrame(extracted_data)
    excel_path = folder_path / "combined_data.xlsx"
    df.to_excel(excel_path, index=False)

    # Append summary to local log file
    now = datetime.now()
    date_str = now.strftime("%d/%m/%y %H:%M:%S")
    summary_message = (
        f"Successfully processed files: {', '.join(success_files) if success_files else 'None'}\n"
        f"Failed files: {', '.join(failed_files) if failed_files else 'None'}\n"
        f"{len(success_files)} files processed and appended to combined_data.xlsx on {date_str}\n"
    )
    with local_log.open("a") as log:
        log.write(summary_message)
    if log_callback:
        log_callback(summary_message)

    # Move folder to 'processed'
    dest_path = PROCESSED / date_folder
    shutil.move(str(folder_path), str(dest_path))
    msg = f"Folder {folder_path.name} moved to {dest_path}"
    print(msg)
    if log_callback:
        log_callback(msg + "\n")

    excel_dest_path = dest_path / "combined_data.xlsx"
    return dest_path, excel_dest_path

def get_original_reg_no(folder_path: Path, filename: str) -> str:
    """
    Reads the file_reg_mapping.txt to get the original registration number
    for a given filename.
    """
    mapping_file = folder_path / "file_reg_mapping.txt"
    if not mapping_file.exists():
        return None
    
    with mapping_file.open("r") as mapping:
        for line in mapping:
            line = line.strip()
            if ":" in line:
                file_name, reg_no = line.split(":", 1)
                if file_name == filename:
                    return reg_no
    return None


if __name__ == "__main__":
    reg_nos_to_move = [
        "9H-SLD",
        # Add more reg_nos as needed
    ]
    move_multiple_files(reg_nos_to_move, datetime.today().strftime("%Y%m%d%H%M%S"))
    # Use the current timestamp for today's folder
    today_str = datetime.today().strftime("%Y%m%d%H%M%S")
    process_pdf_folder(today_str)

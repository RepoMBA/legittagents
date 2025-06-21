import shutil
from pathlib import Path
from datetime import datetime
import shutil
from pathlib import Path
from datetime import datetime
import pandas as pd
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from Helper.extract_pdf_to_excel import data_retriever as extract_data_from_pdf



# Constants for base directories
DATABASE_DIR = Path("./Database")
TO_BE_PROCESSED = DATABASE_DIR / "To_Be_Processed"
PROCESSING = DATABASE_DIR / "Processing"
PROCESSED = DATABASE_DIR / "Processed"
LOG_FOLDER = TO_BE_PROCESSED / "move_logs" 
TODAY_STR = datetime.today().strftime("%Y%m%d%H%M%S")
DATE_STR = datetime.today().strftime("%d/%m/%y %H:%M:%S")

def init_directories():
    PROCESSING.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)

init_directories()


def get_today_folder() -> Path:
    """Returns the processing folder path for today's date, creating it if necessary."""
    today_folder = PROCESSING / TODAY_STR
    today_folder.mkdir(parents=True, exist_ok=True)
    return today_folder

def log_move(filename: str, reg_no: str):
    """Appends a log entry about a moved file."""
    log_dir = LOG_FOLDER
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = LOG_FOLDER / f"{TODAY_STR}.log"
    with log_file.open("a") as log:
        # log.write(f"{filename} from folder {reg_no} moved to {TODAY_STR} folder on date {DATE_STR}\n")
        log.write(f"{filename} from folder {reg_no} moved to processing folder {TODAY_STR} on date {DATE_STR}\n")

def move_file(filename: str, reg_no: str):
    """
    Moves a file from to_be_processed/[REG_NO]/ to processing/[TODAY'S_DATE]/
    and logs the move.
    """
    src = TO_BE_PROCESSED / reg_no / filename
    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist.")

    dest_folder = get_today_folder()
    # shutil.move(str(src), str(dest_folder / filename))
    shutil.copy2(str(src), str(dest_folder / filename))

    log_move(filename, reg_no)
    print(f"Moved {filename} from {reg_no} to {dest_folder}")

def move_multiple_files(file_reg_list):
    """
    Moves multiple files. 
    file_reg_list: List of tuples like [("fileA.pdf", "123"), ("fileB.pdf", "456")]
    """
    for filename, reg_no in file_reg_list:
        try:
            move_file(filename, reg_no)
        except Exception as e:
            print(f"Error moving {filename} from {reg_no}: {e}")




def process_pdf_folder(date_folder: str):
    """
    Processes all PDFs in the specified date folder (format: DD-MM-YY),
    saves a single Excel file, appends to local log, and moves the folder.
    """
    folder_path = PROCESSING / date_folder
    if not folder_path.exists():
        raise FileNotFoundError(f"No such processing folder: {folder_path}")

    pdf_files = list(folder_path.glob("*.pdf"))
    if not pdf_files:
        raise ValueError("No PDF files found in folder")

    # Extract data
    extracted_data = []
    for pdf_file in pdf_files:
        try:
            data = extract_data_from_pdf(pdf_file)
            extracted_data.append(data)
        except Exception as e:
            print(f"Error reading {pdf_file.name}: {e}")

    # Write to Excel
    df = pd.DataFrame(extracted_data)
    excel_path = folder_path / "combined_data.xlsx"
    df.to_excel(excel_path, index=False)

    # Append to local log file
    local_log = folder_path / "processing_log.log"
    # if not local_log.exists():
    #     raise FileNotFoundError(f"Log file not found in folder: {local_log}")


    with local_log.open("a") as log:
        log.write(f"{len(pdf_files)} files processed and appended to combined_data.xlsx on {DATE_STR}\n")

    # Move folder to 'processed'
    dest_path = PROCESSED / date_folder
    shutil.move(str(folder_path), str(dest_path))
    print(f"Folder {folder_path.name} moved to {dest_path}")

    return dest_path


if __name__ == "__main__":
    files_to_move = [
        ("9H-SLE005382.pdf", "9H-SLE"),
        ("9H-SLD004310.pdf", "9H-SLD"),
    ]
    move_multiple_files(files_to_move)
    process_pdf_folder(TODAY_STR)
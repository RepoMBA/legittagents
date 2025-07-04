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
from Helpers.extract_text_from_pdf import data_retriever as extract_data_from_pdf

# Constants for base directories
DATABASE_DIR = Path("/Users/shresthkansal/LegittAI/legittagents/Database")
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

def get_today_folder(date_str: str = TODAY_STR) -> Path:
    """Returns the processing folder path for the given date key (YYYYMMDDhhmmss)."""
    today_folder = PROCESSING / date_str
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

def move_file(filepath: str, reg_no: str, date_str: str = TODAY_STR):
    """
    Moves a file from to_be_processed/[REG_NO]/ to processing/[TODAY'S_DATE]/
    and logs the move.
    """


    full_path = Path(filepath)
    filename = full_path.name
    src = TO_BE_PROCESSED / reg_no / filename
    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist.")

    dest_folder = get_today_folder(date_str)
    # shutil.move(str(src), str(dest_folder / filename))
    print(dest_folder)
    shutil.copy2(str(src), f"{dest_folder}/{filename}")

    log_move(filename, reg_no)
    print(f"Moved {filename} from {reg_no} to {dest_folder}")

def move_multiple_files(reg_no_list, date_str: str = TODAY_STR, log_callback=None):
    """Move all PDFs under each reg_no into PROCESSING/date_str."""
    for reg_no in reg_no_list:
        folder_path = TO_BE_PROCESSED / reg_no
        if not folder_path.exists():
            log_callback and log_callback(f"No such folder: {folder_path}\n")
            continue

        for pdf in folder_path.glob("*.pdf"):
            try:
                move_file(pdf, reg_no, date_str)
                log_callback and log_callback(f"Moved {pdf.name} from {reg_no}\n")
            except Exception as e:
                log_callback and log_callback(f"Error moving {pdf.name} from {reg_no}: {e}\n")


def assign_rotations(df, date_col='Date', dep_col='Dep', arr_col='Arr'):
    # 1) Copy, parse & sort by date
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], format='%d-%b-%y')
    df = df.sort_values(date_col).reset_index(drop=True)

    # 2) Filter out no‐takeoff flights
    valid = df[df[dep_col] != df[arr_col]].copy()
    valid_indices = valid.index.tolist()
    n = len(valid_indices)

    # 3) Prepare positional rotation series and a single global counter
    rotations = pd.Series(0, index=range(n), dtype=int)
    global_rotation = 0
    i = 0

    # 4) Walk through valid flights, closing or abandoning loops immediately
    while i < n:
        start_dep = valid.iloc[i][dep_col]
        current_rot = global_rotation + 1

        loop_positions = [i]
        last_arr = valid.iloc[i][arr_col]
        j = i + 1

        # Continue as long as next departure matches the last arrival
        while j < n and valid.iloc[j][dep_col] == last_arr:
            loop_positions.append(j)
            last_arr = valid.iloc[j][arr_col]
            if last_arr == start_dep:
                # closed this loop
                break
            j += 1

        # Assign the same rotation number to all collected legs
        for pos in loop_positions:
            rotations.at[pos] = current_rot

        # Bump the global counter
        global_rotation = current_rot

        # Advance i:
        # – If we closed the loop (last_arr == start_dep), skip past the closer
        # – Otherwise (chain‐break), abandon immediately and start at j
        if j < n and last_arr == start_dep:
            i = j + 1
        else:
            i = j

    # 5) Map back into the original DataFrame
    df['Rotation'] = 0
    for pos, orig_idx in enumerate(valid_indices):
        df.loc[orig_idx, 'Rotation'] = rotations.at[pos]

    return df



def process_pdf_folder(date_folder: str, log_callback=None):
    """
    Processes all PDFs in the specified date folder (format: DD-MM-YY),
    saves a single Excel file, appends to local log, and moves the folder.
    """

    folder_path = PROCESSING / date_folder
    print(folder_path)
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
    df = assign_rotations(df)
    excel_path = folder_path / "combined_data.xlsx"
    df['Date'] = df['Date'].dt.strftime('%d-%b-%y')
    df.to_excel(excel_path, index=False)

    # Append to local log file
    local_log = folder_path / "processing_log.log"
    local_log.parent.mkdir(parents=True, exist_ok=True)


    with local_log.open("a") as log:
        log.write(f"{len(pdf_files)} files processed and appended to combined_data.xlsx on {DATE_STR}\n")

    # Move folder to 'processed'
    dest_path = PROCESSED / date_folder
    shutil.move(str(folder_path), str(dest_path))
    print(f"Folder {folder_path.name} moved to {dest_path}")
    log_callback and log_callback(f"Folder {folder_path.name} moved to {dest_path}\n")

    return dest_path, excel_path


def main():
    move_multiple_files('9H-SLI')
    process_pdf_folder(TODAY_STR)

if __name__ == "__main__":
    main()

    



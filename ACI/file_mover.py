import shutil
from pathlib import Path
from datetime import datetime
import pandas as pd
import sys
from config import DATABASE_DIRECTORY

sys.path.append(str(Path(__file__).resolve().parent.parent))
from Helpers.extract_text_from_pdf import data_retriever as extract_data_from_pdf

# Constants for base directories
DATABASE_PATH = Path(DATABASE_DIRECTORY)
TO_BE_PROCESSED = DATABASE_PATH / "To_Be_Processed"
PROCESSING = DATABASE_PATH / "Processing"
PROCESSED = DATABASE_PATH / "Processed"
LOG_FOLDER = TO_BE_PROCESSED / "move_logs" 
TODAY_STR = datetime.today().strftime("%Y-%m-%d_%H-%M")
DATE_STR = datetime.today().strftime("%d/%m/%y %H:%M:%S")


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
    today_str = now.strftime("%Y-%m-%d_%H-%M")  # Use consistent format
    date_str = now.strftime("%d/%m/%y %H:%M:%S")
    log_file = LOG_FOLDER / f"{TODAY_STR}.log"  # Log file named with consistent format
    log_message = f"{filename} from folder {reg_no} moved to processing folder {TODAY_STR} on date {date_str}\n"
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


def _blank(x):
    return pd.isna(x) or (isinstance(x, str) and x.strip() == '')


def assign_rotations(df, date_col='Date', dep_col='Dep', arr_col='Arr', reg_col='Registration', atd_col='ATD', to_col='TO', ldg_col='LDG'):
    # 1) Copy, parse & sort by date
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], format='%d-%b-%y')

    # parse ATD strings like '04:21' into timestamps (default date = 1900-01-01)
    df[atd_col] = pd.to_datetime(df[atd_col], format='%H:%M', errors='coerce')
    df[atd_col] = df[atd_col].dt.strftime('%H:%M')

    # 2) Sort by Registration → Date → ATD
    df = df.sort_values(by=[reg_col, date_col, atd_col]).reset_index(drop=True)

    # df = df.sort_values(date_col).reset_index(drop=True)
    
    # 2) Add Status column based on takeoff status
    # df['Status'] = df.apply(lambda row: 'Cancelled' if row[dep_col] == row[arr_col] else 'Completed', axis=1)
    df['Status'] = df.apply(
        lambda row: (
            'Not Flown'
            if (_blank(row[to_col]) and _blank(row[ldg_col]))
            else ('Cancelled' if row[dep_col] == row[arr_col] else 'Completed')
        ),
        axis=1
    )
    
    # 3) Filter out no‐takeoff flights
    valid = df[df[dep_col] != df[arr_col]].copy()
    valid_indices = valid.index.tolist()
    n = len(valid_indices)

    # 4) Prepare positional rotation series and a single global counter
    rotations = pd.Series(0, index=range(n), dtype=int)
    global_rotation = 0
    i = 0

    # 5) Walk through valid flights, closing or abandoning loops immediately
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

    # 6) Map back into the original DataFrame
    df['Rotation'] = 0
    for pos, orig_idx in enumerate(valid_indices):
        df.loc[orig_idx, 'Rotation'] = rotations.at[pos]

    return df


def drop_all_dupe_keys(df, key_cols=("EnquiryNo", "Date", "FlightNumber")):
    """
    Remove every row that shares a duplicate composite key.
    (i.e., if a key appears N>1 times, drop all N rows)
    """
    tmp = df.copy()
    # Normalize strings to avoid whitespace-caused misses
    for c in key_cols:
        if c in tmp.columns and tmp[c].dtype == object:
            tmp[c] = tmp[c].str.strip()
    dupe_mask = tmp.duplicated(subset=list(key_cols), keep=False)
    return df.loc[~dupe_mask].copy()


def process_pdf_folder(date_folder: str, log_callback=None):
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
                
                # Add filename to the extracted data
                data['filename'] = pdf_file.name
                
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
    df = assign_rotations(df)
    excel_path = folder_path / "combined_data.xlsx"
    excel_path_2 = folder_path / "combined_data_extended.xlsx"
    df.rename(columns={'DelayDuration': 'Duration'}, inplace=True)
    df.drop(columns=['DelayReason'], inplace=True)
    df['Date'] = df['Date'].dt.strftime('%d-%b-%y')
    df['DelayCode'] = df['DelayCode'].str.split('/').str[0]
    df_extended = df.copy()
    df_extended.to_excel(excel_path_2, index=False)
    # df.drop(columns=['filename'], inplace=True)
    # df.to_excel(excel_path, index=False)
    df_combined = df[df['Status'] != 'Not Flown'].copy()
    df_combined = drop_all_dupe_keys(df_combined, ("EnquiryNo", "Date", "FlightNumber"))    # To Remove all Duplicates
    df_combined.drop(columns=['filename'], inplace=True)
    df_combined.to_excel(excel_path, index=False)

   # Append summary to local log file
    now = datetime.now()
    date_str = now.strftime("%d/%m/%y %H:%M:%S")
    summary_message = (
        f"Successfully processed files: {', '.join(success_files) if success_files else 'None'}\n"
        f"Failed files: {', '.join(failed_files) if failed_files else 'None'}\n"
        f"{len(success_files)} files processed and appended to combined_data.xlsx on {date_str}\nData Extraction Completed Successfully!!\n"
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
    move_multiple_files(reg_nos_to_move, TODAY_STR)
    # Use the current timestamp for today's folder
    process_pdf_folder(TODAY_STR)

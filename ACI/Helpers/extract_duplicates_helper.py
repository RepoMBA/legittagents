from pathlib import Path
import pandas as pd

SHEET_NAME   = 0                        # 0 = first sheet, or use a sheet name like "Sheet1"
KEY_COLS     = ("EnquiryNo", "Date", "FlightNumber")  # duplicate-detection key


def extract_duplicates_from_file(folder_path:str, file_name:str = "combined_data_extended.xlsx"):
    xlsx_path = Path(folder_path + '/' + file_name)
    df = pd.read_excel(xlsx_path, sheet_name=SHEET_NAME, engine="openpyxl")
    missing = [c for c in KEY_COLS if c not in df.columns]
    if missing:
        raise(
            f"Missing Key Columns : {missing}"
            f"Available Columns : {list(df.columns)}"
        )
    
    status_col = next((c for c in df.columns if c.lower() == "status"), None)

    not_flown_df = pd.DataFrame(columns=df.columns)
    if status_col is not None:
        status_series = df[status_col].astype(str).str.strip().str.casefold()
        not_flown_df = df[status_series == "not flown"].copy()
        # keep only rows that are NOT "Not Flown"
        df = df[status_series != "not flown"].copy()
    
    key_df = df[list(KEY_COLS)].copy()
    if "Date" in KEY_COLS:
        key_df["Date"] = pd.to_datetime(key_df["Date"], errors="coerce").dt.normalize()

    dup_mask = key_df.duplicated(keep=False)
    duplicates = df.loc[dup_mask].copy()
    duplicates = duplicates.assign(AIReason="Duplicate flight number on same date.")

    # Construct the output path correctly using pathlib
    # out_path = Path(folder_path) / "duplicates.xlsx"
    # if not duplicates.empty:
    #     with pd.ExcelWriter(out_path, engine = "openpyxl") as writer:
    #         duplicates.to_excel(writer, index=False, sheet_name="Duplicates")

    #     return folder_path + "/" + "duplicates.xlsx"
    
    # return None

    out_path = Path(folder_path) / "duplicates.xlsx"

    # write only the non-empty sheets
    if not duplicates.empty or not not_flown_df.empty:
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            if not duplicates.empty:
                duplicates.to_excel(writer, index=False, sheet_name="Duplicates")
            if not not_flown_df.empty:
                not_flown_df.to_excel(writer, index=False, sheet_name="Not_flown")
        return str(out_path)

    return None
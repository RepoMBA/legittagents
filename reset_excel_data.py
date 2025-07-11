#!/usr/bin/env python3
"""
Reset Excel Data

This script deletes the existing Excel tracking file from Google Drive
and forces a new one to be created with fresh data.
"""

import os
import sys
import io
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.credentials import google, global_cfg
from Utils.google_drive import download_excel_from_drive

# Get credentials and configuration
gcreds = google()
global_cfg = global_cfg()

# ---------- Global Configuration ----------
DATABASE = global_cfg["blog_content_database"]
EXCEL_NAME = global_cfg["excel_name"]

# ---------- Drive Configuration ----------
SERVICE_ACCOUNT_FILE = gcreds["service_account_json"]
DRIVE_SCOPES = [gcreds["drive_scope"]]
FOLDER_ID = gcreds["drive_folder_id"]
SHARED_DRIVE_ID = gcreds["shared_drive_id"]

DRIVE_KWARGS = {"supportsAllDrives": True}
LIST_KWARGS = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}

if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

def main():
    print("Initializing Drive API client...")
    drive_creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=DRIVE_SCOPES,
    )
    drive = build("drive", "v3", credentials=drive_creds)
    
    # Find the existing Excel file
    print(f"Searching for existing Excel file: {EXCEL_NAME}")
    query = f"name = '{EXCEL_NAME}' and '{FOLDER_ID}' in parents"
    res = drive.files().list(q=query, fields="files(id,name)", **LIST_KWARGS).execute()
    files = res.get("files", [])
    
    if files:
        file_id = files[0]["id"]
        print(f"Found existing Excel file with ID: {file_id}")
        
        # Delete the file
        print("Deleting the existing Excel file...")
        drive.files().delete(fileId=file_id, **DRIVE_KWARGS).execute()
        print("File deleted successfully.")
    else:
        print("No existing Excel file found.")
    
    # Force creation of a new Excel file by calling download_excel_from_drive
    print("Creating new Excel file with fresh data...")
    excel_data = download_excel_from_drive()
    
    if 'file_id' in excel_data:
        print(f"New Excel file created with ID: {excel_data['file_id']}")
        
        # Print sheet information
        for sheet_name, df in excel_data.items():
            if sheet_name != 'file_id':
                print(f"Sheet '{sheet_name}' created with {len(df)} rows")
    else:
        print("Failed to create new Excel file!")
    
    print("Done!")

if __name__ == "__main__":
    main() 
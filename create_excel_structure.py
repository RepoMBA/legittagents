#!/usr/bin/env python3
"""
Create Excel Structure

This script creates a fresh Excel file with the new three-sheet structure
and uploads it to Google Drive, replacing the old file if it exists.
"""

import os
import pandas as pd
from core.credentials import global_cfg, google, users
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from typing import Dict, Any

# Get configuration
cfg = global_cfg()
gcreds = google()
DATABASE = cfg["blog_content_database"]
EXCEL_NAME = cfg["excel_name"]
EXCEL_PATH = os.path.join(DATABASE, EXCEL_NAME)

# Ensure directory exists
os.makedirs(os.path.dirname(EXCEL_PATH) or '.', exist_ok=True)

# Google Drive setup
SERVICE_ACCOUNT_FILE = gcreds["service_account_json"]
DRIVE_SCOPE = [gcreds["drive_scope"]]
FOLDER_ID = gcreds["drive_folder_id"]
SHARED_DRIVE_ID = gcreds["shared_drive_id"]

DRIVE_KWARGS = {"supportsAllDrives": True}
LIST_KWARGS: Dict[str, Any] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
if SHARED_DRIVE_ID:
    # Convert to Dict[str, Any] to fix linter error
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

# Initialize Drive API client
drive_creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=DRIVE_SCOPE,
)
drive = build("drive", "v3", credentials=drive_creds)

# Define column structures for the sheets
ARTICLES_COLUMNS = [
    "id", "filename", "date", "posted_medium", "keyword", "medium_url"
]

SOCIAL_ACCOUNTS_COLUMNS = [
    "id", "employee_name", "platform"
]

SOCIAL_POSTS_COLUMNS = [
    "id", "employee_name", "platform", "article_id", "posted", "post_date", "post_url"
]

print(f"Creating new Excel file at: {EXCEL_PATH}")
print(f"Database directory: {DATABASE}")
print(f"Excel filename: {EXCEL_NAME}")

# Create empty dataframes with correct column types
articles_df = pd.DataFrame({
    "id": pd.Series(dtype="int"),
    "filename": pd.Series(dtype="str"),
    "date": pd.Series(dtype="str"),
    "posted_medium": pd.Series(dtype="bool"),
    "keyword": pd.Series(dtype="str"),
    "medium_url": pd.Series(dtype="str")
})

# Create social_accounts dataframe and populate with existing users
social_accounts_df = pd.DataFrame({
    "id": pd.Series(dtype="int"),
    "employee_name": pd.Series(dtype="str"),
    "platform": pd.Series(dtype="str"),
})

# Pre-populate social accounts from credentials
social_account_id = 1
for user_id, user_data in users().items():
    # Add Twitter accounts
    if 'twitter' in user_data:
        screen_name = user_data.get('twitter', {}).get('screen_name', '')
        if screen_name:
            social_accounts_df = pd.concat([social_accounts_df, pd.DataFrame([{
                "id": social_account_id,
                "employee_name": user_id,
                "platform": "twitter"            }])], ignore_index=True)
            social_account_id += 1
    
    # Add LinkedIn accounts
    if 'linkedin' in user_data:
        social_accounts_df = pd.concat([social_accounts_df, pd.DataFrame([{
            "id": social_account_id,
            "employee_name": user_id,
            "platform": "linkedin",
        }])], ignore_index=True)
        social_account_id += 1

# Create social_posts dataframe
social_posts_df = pd.DataFrame({
    "id": pd.Series(dtype="int"),
    "employee_name": pd.Series(dtype="str"),
    "platform": pd.Series(dtype="str"),
    "article_id": pd.Series(dtype="int"),
    "posted": pd.Series(dtype="bool"),
    "post_date": pd.Series(dtype="str"),
    "post_url": pd.Series(dtype="str")
})

# Write to Excel with all three sheets
with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
    articles_df.to_excel(writer, sheet_name='articles', index=False)
    social_accounts_df.to_excel(writer, sheet_name='social_accounts', index=False)
    social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)

print(f"Created Excel file locally with three sheets")

# Check if the file already exists on Drive
query = f"name = '{EXCEL_NAME}' and '{FOLDER_ID}' in parents"
result = drive.files().list(q=query, fields="files(id,name)", **LIST_KWARGS).execute()
files = result.get("files", [])

if files:
    # Update existing file
    file_id = files[0]["id"]
    print(f"Found existing file on Drive with ID: {file_id}")
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    updated_file = drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    print(f"Updated existing file on Drive: {updated_file['id']}")
else:
    # Create new file
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    metadata = {"name": EXCEL_NAME, "parents": [FOLDER_ID]}
    created_file = drive.files().create(body=metadata, media_body=media, fields="id", **DRIVE_KWARGS).execute()
    print(f"Created new file on Drive: {created_file['id']}")

print("Done!") 
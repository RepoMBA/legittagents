#!/usr/bin/env python3
"""
Google Drive Utilities

This module contains shared functions for interacting with Google Drive,
particularly for handling Excel files and tracking article publications.
"""

import os
import io
from typing import Dict, Any, Tuple, List, Optional, cast

import pandas as pd
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from core.credentials import google, global_cfg, users

# Get credentials and configuration
gcreds = google()
global_cfg = global_cfg()

# ---------- Global Configuration ----------
DATABASE: str = global_cfg["blog_content_database"]
EXCEL_NAME: str = global_cfg["excel_name"]

# ---------- Drive Configuration ----------
SERVICE_ACCOUNT_FILE = gcreds["service_account_json"]
DRIVE_SCOPES: list[str] = [gcreds["drive_scope"]]
FOLDER_ID: str = gcreds["drive_folder_id"]
SHARED_DRIVE_ID: str = gcreds["shared_drive_id"]

DRIVE_KWARGS: dict[str, object] = {"supportsAllDrives": True}
LIST_KWARGS: dict[str, object] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}

if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

# Initialize Drive API client
drive_creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=DRIVE_SCOPES,
)
drive = build("drive", "v3", credentials=drive_creds)

# ---------- Excel Configuration ----------
EXCEL_PATH: str = os.path.join(DATABASE, EXCEL_NAME)
os.makedirs(os.path.dirname(EXCEL_PATH) or '.', exist_ok=True)

# Define column structures for both sheets
ARTICLES_COLUMNS = [
    "id", "filename", "date", "posted_medium", "keyword", "medium_url"
]

SOCIAL_ACCOUNTS_COLUMNS = [
    "id", "employee_name", "platform"
]

SOCIAL_POSTS_COLUMNS = [
    "id", "employee_name", "platform", "article_id", "posted", "post_date", "post_url"
]

def ensure_excel_on_drive() -> str:
    """Return file id of tracking Excel, creating it if missing."""
    query = f"name = '{EXCEL_NAME}' and '{FOLDER_ID}' in parents"
    res = drive.files().list(q=query, fields="files(id,name)", **LIST_KWARGS).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    # Create a new Excel file with all three sheets
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        # Create articles sheet
        df_articles = pd.DataFrame()
        for col in ARTICLES_COLUMNS:
            df_articles[col] = pd.Series(dtype=object)
        df_articles.to_excel(writer, sheet_name='articles', index=False)
        
        # Create social_accounts sheet
        df_social_accounts = pd.DataFrame({
            "id": pd.Series(dtype=int),
            "employee_name": pd.Series(dtype=str),
            "platform": pd.Series(dtype=str),
        })
        
        # Pre-populate social accounts from credentials
        account_id = 1
        all_users = users()
        for user_id, user_data in all_users.items():
            # Add Twitter accounts
            if 'twitter' in user_data:
                screen_name = user_data.get('twitter', {}).get('screen_name', '')
                if screen_name:
                    new_row = pd.DataFrame([{
                        "id": account_id,
                        "employee_name": user_id,
                        "platform": "twitter",
                    }])
                    df_social_accounts = pd.concat([df_social_accounts, new_row], ignore_index=True)
                    account_id += 1
            
            # Add LinkedIn accounts
            if 'linkedin' in user_data:
                new_row = pd.DataFrame([{
                    "id": account_id,
                    "employee_name": user_id,
                    "platform": "linkedin",
                }])
                df_social_accounts = pd.concat([df_social_accounts, new_row], ignore_index=True)
                account_id += 1
                
        df_social_accounts.to_excel(writer, sheet_name='social_accounts', index=False)
        
        # Create social_posts sheet with correct structure
        df_social = pd.DataFrame({col: pd.Series(dtype=object) for col in SOCIAL_POSTS_COLUMNS})
        df_social.to_excel(writer, sheet_name='social_posts', index=False)

    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    meta = {"name": EXCEL_NAME, "parents": [FOLDER_ID]}
    file = drive.files().create(body=meta, media_body=media, fields="id", **DRIVE_KWARGS).execute()
    print(f"[INFO] Created tracking Excel on Drive (id={file['id']}) with articles, social_accounts, and social_posts sheets")
    return file["id"]

def download_excel_from_drive() -> Dict[str, pd.DataFrame]:
    """
    Downloads the tracking Excel file from Google Drive.
    
    Returns:
        Dict with DataFrames for each sheet and the file ID as 'file_id'
    """
    file_id = ensure_excel_on_drive()
    request = drive.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    
    # Read all sheets
    result: Dict[str, Any] = {
        'file_id': file_id,
    }
    
    try:
        # Try to read all sheets in the new format
        xl = pd.ExcelFile(fh)
        sheet_names = xl.sheet_names
        
        if 'articles' in sheet_names:
            result['articles'] = pd.read_excel(fh, sheet_name='articles', dtype={'medium_url': str})
        
        if 'social_accounts' in sheet_names:
            result['social_accounts'] = pd.read_excel(fh, sheet_name='social_accounts')
        
        if 'social_posts' in sheet_names:
            result['social_posts'] = pd.read_excel(fh, sheet_name='social_posts', dtype={'post_url': str})
            
        # Check if we got at least the articles sheet in the new format
        if 'articles' in result:
            return result
            
        # If we get here, it means the Excel exists but not with the expected sheet names
        print("[WARN] Excel file exists but doesn't have the expected sheets.")
        
    except Exception as e:
        print(f"[ERROR] Failed to read Excel sheets: {e}")
    
    # If we get here, we need to create the proper structure
    print("[INFO] Creating new Excel structure...")
    
    # Create empty dataframes with correct column types
    articles_df = pd.DataFrame({
        "id": pd.Series(dtype="int"),
        "filename": pd.Series(dtype="str"),
        "date": pd.Series(dtype="str"),
        "posted_medium": pd.Series(dtype="bool"),
        "keyword": pd.Series(dtype="str"),
        "medium_url": pd.Series(dtype="str")
    })
    
    # Create social_accounts dataframe
    social_accounts_df = pd.DataFrame({
        "id": pd.Series(dtype="int"),
        "employee_name": pd.Series(dtype="str"),
        "platform": pd.Series(dtype="str"),
    })
    
    # Pre-populate social accounts from credentials
    account_id = 1
    all_users = users()
    for user_id, user_data in all_users.items():
        # Add Twitter accounts
        if 'twitter' in user_data:
            new_row = pd.DataFrame([{
                "id": account_id,
                "employee_name": user_id,
                "platform": "twitter",
            }])
            social_accounts_df = pd.concat([social_accounts_df, new_row], ignore_index=True)
            account_id += 1
        
        # Add LinkedIn accounts
        if 'linkedin' in user_data:
            new_row = pd.DataFrame([{
                "id": account_id,
                "employee_name": user_id,
                "platform": "linkedin",
            }])
            social_accounts_df = pd.concat([social_accounts_df, new_row], ignore_index=True)
            account_id += 1
    
    # Create social_posts dataframe
    social_posts_df = pd.DataFrame({col: pd.Series(dtype="object") for col in SOCIAL_POSTS_COLUMNS})
    
    # Save all sheets
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        articles_df.to_excel(writer, sheet_name='articles', index=False)
        social_accounts_df.to_excel(writer, sheet_name='social_accounts', index=False)
        social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)
    
    # Upload the new file
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    
    # Return the new dataframes
    result = {
        'file_id': file_id,
        'articles': articles_df,
        'social_accounts': social_accounts_df,
        'social_posts': social_posts_df
    }
    
    return result

def update_medium_article(filename: str, updates: dict) -> int:
    """
    Updates an existing Medium article entry in the articles sheet.
    
    Args:
        filename: The filename to match for updating
        updates: Dictionary of column-value pairs to update
    
    Returns:
        int: The article ID
        
    Raises:
        ValueError: If the file doesn't contain the filename column or if no matching entry is found
    """
    excel_data = download_excel_from_drive()
    file_id = excel_data['file_id']
    articles_df = excel_data['articles']
    social_accounts_df = excel_data['social_accounts']
    social_posts_df = excel_data['social_posts']

    if "filename" not in articles_df.columns:
        raise ValueError("Articles sheet is missing 'filename' column.")

    # Find the matching row
    match = articles_df["filename"] == filename
    if not match.any():
        raise ValueError(f"No entry found for filename: {filename}")

    # Update the articles sheet
    for key, value in updates.items():
        articles_df.loc[match, key] = value
    
    # Get the article ID
    article_id = articles_df.loc[match, "id"].iloc[0]
    
    
    # Save the updated Excel file
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        articles_df.to_excel(writer, sheet_name='articles', index=False)
        social_accounts_df.to_excel(writer, sheet_name='social_accounts', index=False)
        social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)
    
    # Upload to Drive
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    
    return article_id

def update_social_post(employee_name: str, platform: str, article_id: int, updates: dict) -> None:
    """
    Updates a social media post entry in the social_posts sheet.
    
    Args:
        employee_name: Employee name
        platform: Platform name (twitter, linkedin)
        article_id: The article ID to match
        updates: Dictionary of column-value pairs to update
        
    Raises:
        ValueError: If no matching entry is found
    """
    excel_data = download_excel_from_drive()
    file_id = excel_data['file_id']
    articles_df = excel_data['articles']
    social_posts_df = excel_data['social_posts']

    # Find the matching row
    match = ((social_posts_df["employee_name"] == employee_name) & 
             (social_posts_df["platform"] == platform) & 
             (social_posts_df["article_id"] == article_id))
             
    if not match.any():
        raise ValueError(f"No entry found for employee: {employee_name}, platform: {platform}, article_id: {article_id}")

    # Update the social posts sheet
    for key, value in updates.items():
        social_posts_df.loc[match, key] = value
    
    # Save ALL sheets while injecting the updated social_posts
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        for sheet_name, df in excel_data.items():
            if sheet_name == 'social_posts':
                social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)
            elif sheet_name == 'articles':
                articles_df.to_excel(writer, sheet_name='articles', index=False)
            else:
                # Preserve any additional sheets (e.g. social_accounts)
                if isinstance(df, pd.DataFrame):
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    # Upload the updated file
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()

def add_new_article_entry(filename: str, keyword: str = "") -> int:
    """
    Adds a new article entry to the articles sheet.
    
    Args:
        filename: The filename of the article
        keyword: The keyword used for the article
        
    Returns:
        int: The new article ID
    """
    excel_data = download_excel_from_drive()
    file_id = excel_data['file_id']
    articles_df = excel_data['articles']
    social_accounts_df = excel_data['social_accounts']
    social_posts_df = excel_data['social_posts']
    
    # Generate new article ID - simple serial number
    new_id = 1
    if not articles_df.empty and 'id' in articles_df.columns and len(articles_df) > 0:
        new_id = int(articles_df["id"].max() + 1)
    
    # Create new article entry
    new_article = {
        'id': new_id,
        'filename': filename,
        'date': pd.Timestamp.now().strftime("%Y-%m-%d"),
        'posted_medium': False,
        'keyword': keyword,
        'medium_url': ""
    }
    
    # Add to dataframe
    articles_df = pd.concat([articles_df, pd.DataFrame([new_article])], ignore_index=True)
    
    # Save all sheets
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        articles_df.to_excel(writer, sheet_name='articles', index=False)
        social_accounts_df.to_excel(writer, sheet_name='social_accounts', index=False)
        social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)
    
    # Upload the updated file
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    
    return new_id

def get_unpublished_filenames(platform: str | None = None, employee_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return social-post tasks that are still *unposted* (posted == False).

    Each returned dict contains:
        article_id   – ID from the social_posts sheet (column article_id)
        filename     – Article filename
        medium_url   – Medium URL of the article
        employee_name – Target employee
        platform      – Target platform
    """
    excel_data = download_excel_from_drive()
    articles_df = cast(pd.DataFrame, excel_data["articles"])
    social_posts_df = cast(pd.DataFrame, excel_data["social_posts"])

    # Filter posts that are not yet posted
    pending_posts: pd.DataFrame = pd.DataFrame(social_posts_df[social_posts_df["posted"] == False])

    # Apply platform / employee filters if provided
    if platform:
        pending_posts = pending_posts[pending_posts["platform"] == platform] # type: ignore
    if employee_name:
        pending_posts = pending_posts[pending_posts["employee_name"] == employee_name] # type: ignore

    if pending_posts.empty:
        return []

    # Need filename & medium_url – join with articles_df (only those already on Medium)
    articles_subset: pd.DataFrame = pd.DataFrame(articles_df[["id", "filename", "medium_url", "posted_medium"]])  # type: ignore[arg-type]
    articles_subset = articles_subset[(articles_subset["posted_medium"] == True) & (articles_subset["medium_url"].notna()) & (articles_subset["medium_url"] != "")] # type: ignore[assignment]

    merged: pd.DataFrame = pending_posts.merge(articles_subset, left_on="article_id", right_on="id", how="inner", suffixes=("_post", "_article"))

    results: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        results.append({
            "article_id": int(row["article_id"]),
            "filename": row["filename"],
            "medium_url": row["medium_url"],
            "employee_name": row["employee_name"],
            "platform": row["platform"],
        })

    return results

def retrieve_file_from_drive_path(path_list: list, parent_id: str) -> bytes:
    """
    Retrieve a file from Google Drive using a path list.
    
    Args:
        path_list: List of folder/file names representing the path
        parent_id: ID of the starting parent folder
        
    Returns:
        bytes: The file contents
        
    Raises:
        FileNotFoundError: If any path segment is not found
    """
    for i, segment in enumerate(path_list):
        is_file = i == len(path_list) - 1
        query = (
            f"'{parent_id}' in parents and "
            f"name = '{segment}' and "
            f"mimeType {'!=' if is_file else '='} 'application/vnd.google-apps.folder' and "
            "trashed = false"
        )
        result = drive.files().list(q=query, fields="files(id, name)", **LIST_KWARGS).execute()
        items = result.get("files", [])
        if not items:
            raise FileNotFoundError(f"{'File' if is_file else 'Folder'} '{segment}' not found under parent ID '{parent_id}'")
        parent_id = items[0]["id"]

    request = drive.files().get_media(fileId=parent_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    return fh.read()

def path_extractor(chosen_file: str, platform: str) -> list:
    """
    Extract Drive path components from a filename.
    
    Args:
        chosen_file: The filename to extract path for
        platform: The platform (twitter, linkedin, etc.)
        
    Returns:
        list: Path components [date_part, platform, platform_filename]
    """
    date_part = chosen_file.split('_')[0]
    file_path = [date_part, platform, f"{platform}_{chosen_file}"]
    return file_path

# Backwards compatibility function
def update_existing_entry(filename: str, updates: dict) -> None:
    """
    Legacy function for backward compatibility.
    Updates an entry in the tracking Excel file.
    """
    # Map old format updates to new format
    new_updates = {}
    
    # Handle medium updates
    if 'posted_on_medium' in updates:
        new_updates['posted_medium'] = updates['posted_on_medium']
    if 'medium_url' in updates:
        new_updates['medium_url'] = updates['medium_url']
    if 'medium_date' in updates:
        new_updates['date'] = updates['medium_date']
    
    # If we have medium updates, apply them to the articles sheet
    if new_updates:
        update_medium_article(filename, new_updates)
    
    # Handle social media updates
    social_updates = {}
    platform = None
    
    # Try to determine which platform this update is for
    if 'posted_on_twitter' in updates:
        platform = 'twitter'
        social_updates['posted'] = updates['posted_on_twitter']
    elif 'posted_on_linkedin' in updates:
        platform = 'linkedin'
        social_updates['posted'] = updates['posted_on_linkedin']
    
    if 'twitter_url' in updates:
        social_updates['post_url'] = updates['twitter_url']
    elif 'linkedin_url' in updates:
        social_updates['post_url'] = updates['linkedin_url']
    
    # If we have social updates, try to apply them
    if platform and social_updates:
        # Need to find the article_id first
        excel_data = download_excel_from_drive()
        articles_df = excel_data['articles']
        
        article_match = articles_df["filename"] == filename
        if article_match.any():
            article_id = articles_df.loc[article_match, "id"].iloc[0]
            
            # Try to update for current user
            active_user = os.environ.get("ACTIVE_USER", None)
            if active_user:
                try:
                    update_social_post(active_user, platform, article_id, social_updates)
                except ValueError:
                    # If not found for current user, just print a warning
                    print(f"[WARN] No matching social post entry found for {active_user} on {platform} for article {article_id}")
            else:
                print("[WARN] No active user set, can't update social post entry")

    if 'social_accounts' not in excel_data:
        excel_data['social_accounts'] = pd.DataFrame(columns=SOCIAL_ACCOUNTS_COLUMNS) # type: ignore
    if 'social_posts' not in excel_data:
        excel_data['social_posts'] = pd.DataFrame(columns=SOCIAL_POSTS_COLUMNS) # type: ignore
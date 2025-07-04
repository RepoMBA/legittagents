# Standard libs
import os
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

# External deps
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import requests
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io

from core.credentials import google, global_cfg, user as _user_creds
gcreds = google()                 # → plain dict
global_cfg = global_cfg()

# Load environment variables
load_dotenv()

# ---------- Global Configuration ----------

DATABASE: str = global_cfg["blog_content_database"]
EXCEL_NAME: str = global_cfg["excel_name"]

# ---------- Drive Configuration ----------
SERVICE_ACCOUNT_FILE = gcreds["service_account_json"]
DRIVE_SCOPES: list[str] = [gcreds["drive_scope"]]
GOOGLE_EMAIL         = gcreds["google_email"]
GOOGLE_PASSWORD      = gcreds["google_password"]
FOLDER_ID: str = gcreds["drive_folder_id"]
SHARED_DRIVE_ID: str = gcreds["shared_drive_id"]
DRIVE_KWARGS: dict[str, object] = {"supportsAllDrives": True}
LIST_KWARGS: dict[str, object] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

drive_creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=DRIVE_SCOPES)
drive = build('drive', 'v3', credentials=drive_creds)

# ---------- Excel Configuration ----------
EXCEL_PATH: str = os.path.join(DATABASE, EXCEL_NAME)
os.makedirs(os.path.dirname(EXCEL_PATH) or '.', exist_ok=True)
EXCEL_COLUMNS = [
    "filename", "date_generated",
    "posted_on_medium", "medium_date", "medium_url",
    "posted_on_twitter", "twitter_date", "twitter_url",
    "posted_on_linkedin", "linkedin_date", "linkedin_url"
]


def retrieve_file_from_drive_path(path_list: list, parent_id: str) -> bytes:

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
    date_part = chosen_file.split('_')[0]
    file_path = [date_part, platform, f"{platform}_{chosen_file}"]
    return file_path

def download_excel_from_drive():
    file_id = ensure_excel_on_drive()
    request = drive.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    df = pd.read_excel(fh, dtype={"medium_url": str})
    return df, file_id

def get_unpublished_filenames(platform):
    df, _ = download_excel_from_drive()
    required_cols = {"posted_on_medium", "posted_on_"+platform, "filename"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Excel must contain columns: {', '.join(missing)}")
    
    mask = (
        (df["posted_on_medium"] == True) &
        (df[f"posted_on_{platform}"] == False)
    )
    # select only the two columns we want
    result_df = df.loc[mask, ["filename", "medium_url"]]
    
    # return as list of dicts: [{"filename": ..., "medium_url": ...}, ...]
    return result_df.to_dict(orient="records")

# ---------- LinkedIn credentials (per ACTIVE_USER) ----------

def post_to_linkedin(
    text_lines: List[str],
    access_token: Optional[str] = None,
    author_urn: Optional[str] = None,
    visibility: str = "PUBLIC",
) -> Dict[str, Any]:
    """
    Publish a LinkedIn post composed of the given lines of text.

    Args:
        text_lines:    List of strings, each a line in the post body.
        access_token:  OAuth2 Bearer token (defaults to env var LINKEDIN_ACCESS_TOKEN).
        author_urn:    LinkedIn author URN (defaults to env var LINKEDIN_AUTHOR_URN),
                       e.g. "urn:li:person:1234ABCD".
        visibility:    "PUBLIC" (default) or "CONNECTIONS" for share visibility.

    Returns:
        The JSON response from LinkedIn on success.

    Raises:
        ValueError: if required credentials are missing.
        Exception: on non-201 response from the API.
    """

    if not access_token or not author_urn:
        raise ValueError(
            "Missing LinkedIn credentials: set LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_URN"
        )

    # Join lines into a single text block
    post_text = "\n".join(text_lines).strip()
    if not post_text:
        raise ValueError("Post text is empty.")

    # Build request
    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }
    payload = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": post_text
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    # Send request
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 201:
        raise Exception(
            f"LinkedIn API error {response.status_code}: {response.text}"
        )

    return response.json()

def update_existing_entry(filename: str, updates: dict):
    df, file_id = download_excel_from_drive()

    if "filename" not in df.columns:
        raise ValueError("Excel is missing 'filename' column.")

    # Find the matching row
    match = df["filename"] == filename
    if not match.any():
        raise ValueError(f"No entry found for filename: {filename}")

    for key, value in updates.items():
        df.loc[match, key] = value

    # Save and upload
    df.to_excel(EXCEL_PATH, index=False)
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()


def ensure_excel_on_drive() -> str:
    """Return file id of tracking Excel, creating it if missing."""
    query = f"name = '{EXCEL_NAME}' and '{FOLDER_ID}' in parents"
    res = drive.files().list(q=query, fields="files(id,name)", **LIST_KWARGS).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    df_blank = pd.DataFrame({c: [] for c in EXCEL_COLUMNS})
    df_blank.to_excel(EXCEL_PATH, index=False)
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    meta = {"name": EXCEL_NAME, "parents": [FOLDER_ID]}
    file = drive.files().create(body=meta, media_body=media, fields="id", **DRIVE_KWARGS).execute()
    print(f"[INFO] Created tracking Excel on Drive (id={file['id']})")
    return file["id"]

def post_linkedin() -> dict:
    # 2) Find target folder
    platform = 'linkedin'
    unpublished_files = get_unpublished_filenames(platform)
    successes: list[dict] = []
    failures: list[dict] = []

    if unpublished_files:
        print(f"Files posted to Medium but not yet to {platform.capitalize()}:")
        for idx, i in enumerate(unpublished_files, 1):
            print(f"{idx}. {i['filename']}")
    else:
        print("No LinkedIn posts pending.")
        return {"status": "nothing_to_publish"}

    for i in unpublished_files:
        # build the Drive path for LinkedIn
        filename = i["filename"]
        medium_url = i["medium_url"]
        file_path = path_extractor(filename, platform)
        
        # fetch and decode the file
        raw = retrieve_file_from_drive_path(file_path, FOLDER_ID)
        text_lines = raw.decode('utf-8').splitlines()
        processed_lines = [line.replace("{{medium_link}}", medium_url) for line in text_lines]

        # -------------------------------------------------
        # LinkedIn credentials (per ACTIVE_USER)
        # -------------------------------------------------
        _li_creds = _user_creds().get("linkedin", {})
        _ACCESS_TOKEN: Optional[str] = _li_creds.get("access_token")
        _AUTHOR_URN: Optional[str] = _li_creds.get("author_urn")

        token = _ACCESS_TOKEN
        urn = _AUTHOR_URN
        if not token or not urn:
            print("[ERROR] Missing LinkedIn token or author URN in credentials JSON")
            failures.append({"filename": filename, "error": "missing_credentials"})
            continue

        try:
            result = post_to_linkedin(processed_lines, token, urn)
            post_id = result.get("id", "")
            post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
            print(f"✅ Post created. Url: {post_url}")
            updates = {
                "posted_on_linkedin": True,
                "linkedin_date": datetime.now().strftime("%Y-%m-%d"),
                "linkedin_url": post_url,
            }
            update_existing_entry(filename = filename, updates = updates)
            successes.append({"filename": filename, "url": post_url})

        except Exception as e:
            print("❌ Failed to post to LinkedIn:", e)
            failures.append({"filename": filename, "error": str(e)})

    return {
        "status": "done",
        "published": successes,
        "failed": failures,
    }

def main():
    post_linkedin()

if __name__ == "__main__":
    main()
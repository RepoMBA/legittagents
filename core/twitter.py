import requests
from typing import List, Dict, Any
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import requests
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io

from typing import Optional

def getenv_required(name: str) -> str:
    v: Optional[str] = os.getenv(name)
    if not v:                         # catches None and empty string
        raise RuntimeError(f"{name} is not set")
    return v

load_dotenv()

# ---------- Configuration ----------
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
DRIVE_SCOPES: list[str] = [os.getenv("DRIVE_SCOPE") or "https://www.googleapis.com/auth/drive"]
FOLDER_ID: str = getenv_required("DRIVE_FOLDER_ID")
GOOGLE_EMAIL         = os.getenv("GOOGLE_EMAIL")
GOOGLE_PASSWORD      = os.getenv("GOOGLE_PASSWORD")

TOKEN_FILE   = getenv_required("TWITTER_TOKEN_FILE")
DATABASE: str = os.getenv("BLOG_CONTENT_DATABASE") or "./Database"
EXCEL_NAME: str = os.getenv("EXCEL_NAME") or "published_articles.xlsx"

# ensure directory exists
EXCEL_PATH: str = os.path.join(DATABASE, EXCEL_NAME)
os.makedirs(os.path.dirname(EXCEL_PATH) or '.', exist_ok=True)

SHARED_DRIVE_ID: str = os.getenv("SHARED_DRIVE_ID") or ""
DRIVE_KWARGS: dict[str, object] = {"supportsAllDrives": True}
LIST_KWARGS: dict[str, object] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

EXCEL_COLUMNS = [
    "filename", "date_generated",
    "posted_on_medium", "medium_date", "medium_url",
    "posted_on_twitter", "twitter_date", "twitter_url",
    "posted_on_linkedin", "linkedin_date", "linkedin_url"
]

def ensure_excel_on_drive() -> str:
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

# -------------------------------------

# Build Drive client once at import time (safe) – Twitter token will now be
# loaded dynamically inside post_twitter() so we don't keep stale credentials.
drive_creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=DRIVE_SCOPES,
)
drive = build("drive", "v3", credentials=drive_creds)
# -------------------------------------

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

def get_unpublished_entries(platform):
    df, _ = download_excel_from_drive()
    required_cols = {"posted_on_medium", "posted_on_"+platform, "filename"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Excel must contain columns: {', '.join(missing)}")
    
    print(f"[INFO] Scanning Excel for {platform} entries to publish…")

    mask = (
        (df["posted_on_medium"] == True) &
        (df[f"posted_on_{platform}"] == False)
    )
    # select only the two columns we want
    result_df = df.loc[mask, ["filename", "medium_url"]]
    
    # return as list of dicts: [{"filename": ..., "medium_url": ...}, ...]
    return result_df.to_dict(orient="records")

def post_to_twitter(text: str, bearer_token: str) -> Dict[str, Any]:
    """
    Sends a tweet with the given text using Twitter API v2.
    """
    url = "https://api.twitter.com/2/tweets"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }
    payload = {"text": text}
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

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

def post_twitter() -> dict:
    platform = "twitter"
    print("[INFO] Starting Twitter publishing run…")

    # Load the latest bearer token and screen name fresh at every invocation
    try:
        with open(TOKEN_FILE) as _tf:
            _creds = json.load(_tf)
            bearer_token = _creds["access_token"]
            screen_name  = _creds["screen_name"]
    except Exception as _err:
        print(f"[ERROR] Could not read Twitter token file: {_err}")
        return {"status": "error", "error": "token_load_failure", "details": str(_err)}

    entries = get_unpublished_entries(platform)

    print(f"[INFO] Found {len(entries)} pending tweet(s) to publish.")

    successes: list[dict] = []
    failures: list[dict] = []

    if entries:
        print(f"[INFO] Files posted to Medium but not yet to {platform.capitalize()}:")
        for idx, entry in enumerate(entries, 1):
            print(f"  {idx}. {entry['filename']}")
    else:
        print("[INFO] No pending tweets to publish.")
        return {"status": "nothing_to_publish"}

    for entry in entries:
        filename   = entry["filename"]
        medium_url = entry["medium_url"]

        # load the draft text
        print(f"[STEP] Loading draft for '{filename}' from Google Drive…")
        file_path = path_extractor(filename, platform)
        raw = retrieve_file_from_drive_path(file_path, FOLDER_ID)
        print("[OK] Draft retrieved; performing placeholder substitutions…")
        text_lines = raw.decode('utf-8').splitlines()
        processed = [line.replace("{{medium_link}}", medium_url) for line in text_lines]
        tweet_text = "\n".join(processed).strip()

        # post the tweet
        print("[STEP] Posting tweet to X/Twitter…")
        try:
            result = post_to_twitter(tweet_text, bearer_token)
            tweet_id = result.get("data", {}).get("id")
            tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}"
            print(f"[SUCCESS] Tweet posted: {tweet_url}")
            updates = {
                f"posted_on_{platform}": True,
                f"{platform}_date": datetime.now().strftime("%Y-%m-%d"),
                f"{platform}_url": tweet_url,
            }
            print("[STEP] Updating Excel tracking sheet…")
            update_existing_entry(filename = filename, updates = updates)
            print("[OK] Excel updated.")

            successes.append({"filename": filename, "url": tweet_url})

        except Exception as e:
            print("[ERROR] Failed to post tweet:", e, filename, tweet_text[0:15])
            failures.append({"filename": filename, "error": str(e)})

    return {
        "status": "done",
        "published": successes,
        "failed": failures,
    }

def main():
    post_twitter()

if __name__ == "__main__":
    main()
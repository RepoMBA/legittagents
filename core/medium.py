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
import random
from typing import Tuple, cast, Dict, List, Optional, Any
from core.credentials import google, global_cfg

gcreds = google()                 # → plain dict
global_cfg = global_cfg()


# ---------- Global Configuration ----------

DATABASE: str = global_cfg["blog_content_database"]
EXCEL_NAME: str = global_cfg["excel_name"]

# ---------- Drive Configuration ----------
GOOGLE_EMAIL         = gcreds["google_email"]
GOOGLE_PASSWORD      = gcreds["google_password"]
SERVICE_ACCOUNT_FILE = gcreds["service_account_json"]
DRIVE_SCOPE             = [gcreds["drive_scope"]]
DRIVE_FOLDER_ID: str = gcreds["drive_folder_id"]
SHARED_DRIVE_ID        = gcreds["shared_drive_id"]
DRIVE_KWARGS: dict[str, object] = {"supportsAllDrives": True}
LIST_KWARGS: dict[str, object] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=DRIVE_SCOPE
)
drive = build("drive", "v3", credentials=creds)

# ---------- Excel Configuration ----------
EXCEL_PATH: str = os.path.join(DATABASE, EXCEL_NAME)
os.makedirs(os.path.dirname(EXCEL_PATH) or '.', exist_ok=True)

# Define column structures for the sheets - matching create_excel_structure.py
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
    """Return the Drive file-id for the tracking Excel.
    If it doesn't exist, create a blank sheet locally and upload it, then
    return the new file id.
    """
    query = f"name = '{EXCEL_NAME}' and '{DRIVE_FOLDER_ID}' in parents"
    result = drive.files().list(q=query, fields="files(id, name)", **LIST_KWARGS).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    # --- bootstrap a fresh sheet with the three-sheet structure ---
    # Create empty dataframes with correct column types
    articles_df = pd.DataFrame({
        "id": pd.Series(dtype="int"),
        "filename": pd.Series(dtype="str"),
        "date": pd.Series(dtype="str"),
        "posted_medium": pd.Series(dtype="bool"),
        "keyword": pd.Series(dtype="str"),
        "medium_url": pd.Series(dtype="str")
    })

    social_accounts_df = pd.DataFrame({
        "id": pd.Series(dtype="int"),
        "employee_name": pd.Series(dtype="str"),
        "platform": pd.Series(dtype="str")
    })

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

    media = MediaFileUpload(
        EXCEL_PATH,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    metadata = {"name": EXCEL_NAME, "parents": [DRIVE_FOLDER_ID]}
    file = drive.files().create(body=metadata, media_body=media, fields="id", **DRIVE_KWARGS).execute()
    print(f"[INFO] Created new tracking sheet on Drive ({file['id']})")
    return file["id"]

def retrieve_file_from_drive_path(path_list: list, parent_id: str) -> bytes:
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID env var is missing")

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

def _retry(fn, attempts: int = 3, delay: float = 1.0):
    """Simple retry helper for transient network/SSL errors."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            if i == attempts:
                raise
            # Only retry on network-layer errors
            if "SSL" in str(e) or "ssl" in str(e).lower() or "HttpError" in type(e).__name__:
                time.sleep(delay * i)
                continue
            raise

def download_excel_from_drive() -> Tuple[Dict[str, pd.DataFrame], str]:
    """
    Download the Excel file from Drive and return a dictionary of dataframes,
    one for each sheet, and the file ID.
    
    Returns:
        Tuple[Dict[str, pd.DataFrame], str]: A tuple containing the dictionary of dataframes
        (one per sheet) and the file ID.
    """
    def _download():
        file_id = ensure_excel_on_drive()
        request = drive.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        # Read all sheets into a dictionary of dataframes
        excel_data = pd.read_excel(fh, sheet_name=None)
        
        # Return the dictionary of dataframes and the file ID
        return excel_data, file_id

    return cast(Tuple[Dict[str, pd.DataFrame], str], _retry(_download))

def get_unpublished_filenames() -> List[str]:
    """
    Get a list of filenames from the articles sheet where posted_medium is False
    """
    excel_data, _ = download_excel_from_drive()
    
    # Check if we have the articles sheet
    if 'articles' not in excel_data:
        raise ValueError("Excel file must contain an 'articles' sheet.")
    
    articles_df = excel_data['articles']
    
    # Check if necessary columns exist
    if "posted_medium" not in articles_df.columns or "filename" not in articles_df.columns:
        raise ValueError("Articles sheet must contain 'posted_medium' and 'filename' columns.")
    
    # Get unpublished filenames
    return articles_df[articles_df["posted_medium"] == False]["filename"].tolist()

def get_next_social_post_id() -> int:
    """Return the next integer ID for the *social_posts* sheet.

    Robust against cases where the ``id`` column exists but contains
    only *NaN* / non-numeric entries (which would make ``max()`` return
    *NaN* and crash when cast to ``int``)."""

    excel_data, _ = download_excel_from_drive()

    # If the sheet is missing or empty → 1
    if 'social_posts' not in excel_data:
        return 1

    social_posts_df = excel_data['social_posts']
    if social_posts_df.empty or 'id' not in social_posts_df.columns:
        return 1

    # Convert to numeric, coercing errors to NaN, then drop NaN rows
    numeric_ids = pd.to_numeric(social_posts_df['id'], errors='coerce')
    numeric_ids_series = numeric_ids.dropna()  # type: ignore[attr-defined]
    if numeric_ids_series.empty:  # type: ignore[attr-defined]
        return 1

    return int(numeric_ids_series.max()) + 1  # type: ignore[call-arg]

def get_article_id_by_filename(filename: str) -> Optional[int]:
    """Get the article ID for a given filename"""
    excel_data, _ = download_excel_from_drive()
    
    if 'articles' not in excel_data:
        raise ValueError("Excel file must contain an 'articles' sheet.")
    
    articles_df = excel_data['articles']
    
    if "id" not in articles_df.columns or "filename" not in articles_df.columns:
        raise ValueError("Articles sheet must contain 'id' and 'filename' columns.")
    
    matching_rows = articles_df[articles_df["filename"] == filename]
    
    if matching_rows.empty:
        return None
    
    return int(matching_rows.iloc[0]["id"])

def shorten_url(url):
    response = requests.get(f"http://tinyurl.com/api-create.php?url={url}")
    return response.text.strip()

def login_medium(page):
    # 1) Go to Medium's mobile sign-in
    page.goto("https://medium.com/m/signin", wait_until="domcontentloaded")
    
    # 2) (Optional) dismiss cookie banner
    try:
        page.click("button:has-text('Accept all')", timeout=5_000)
        page.wait_for_timeout(1_000)
    except PlaywrightTimeoutError:
        pass

    # 3) Click "Sign in with Google"
    page.wait_for_selector("a:has-text('Sign in with Google')", timeout=10_000)
    page.click("a:has-text('Sign in with Google')")

    # 4) Google login
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.fill("input#identifierId", GOOGLE_EMAIL)
    page.click("button:has-text('Next')")
    page.wait_for_selector("input[type='password']", timeout=10_000)
    page.fill("input[type='password']", GOOGLE_PASSWORD)
    page.click("button:has-text('Next')")

    # 5) Wait to be back on Medium
    page.wait_for_selector("a[data-testid='headerWriteButton']", timeout=30_000)

def post_to_medium(page, title: str, content: str):
    page.goto("https://medium.com/", wait_until="networkidle")
    page.wait_for_selector('a[data-testid="headerWriteButton"]', timeout=10_000)
    page.click('a[data-testid="headerWriteButton"]')

    title_h3 = page.locator("h3[data-testid='editorTitleParagraph']")
    title_h3.wait_for(timeout=15_000)
    time.sleep(1)

    title_h3.click()
    page.keyboard.type(title)

    body_para = page.locator("p[data-testid='editorParagraphText']")
    body_para.wait_for(timeout=15_000)

    page.click("p[data-testid='editorParagraphText']", timeout=10_000)
    lines = content.split("\n")
    for i, line in enumerate(lines):
        page.keyboard.type(line)
        if i < len(lines) - 1:
            page.keyboard.press("Shift+Enter")

    page.click("button[data-action='show-prepublish']", timeout=10_000)    
    page.wait_for_selector(
        "button[data-action='show-prepublish']:not(.button--disabledPrimary)",
        timeout=15_000
    )

    page.click('p[data-testid="editorParagraphText"] >> text="Add a topic…"', timeout=10_000)
    page.keyboard.type("smart contracts")
    page.keyboard.press("Enter")

    with page.expect_navigation():
        page.click("button[data-testid='publishConfirmButton']", timeout=10_000)

    article_url = page.url
    page.wait_for_timeout(3_000)

    return article_url


def update_article_entry(filename: str, updates: dict):
    """Update an article entry in the articles sheet"""
    excel_data, file_id = download_excel_from_drive()
    
    if 'articles' not in excel_data:
        raise ValueError("Excel file must contain an 'articles' sheet.")
    
    articles_df = excel_data['articles']
    
    if "filename" not in articles_df.columns:
        raise ValueError("Articles sheet is missing 'filename' column.")

    # Find the matching row
    match = articles_df["filename"] == filename
    if not match.any():
        raise ValueError(f"No entry found for filename: {filename}")

    # Update the article entry
    for key, value in updates.items():
        articles_df.loc[match, key] = value

    # Save and upload
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        articles_df.to_excel(writer, sheet_name='articles', index=False)
        
        # Preserve other sheets
        for sheet_name, df in excel_data.items():
            if sheet_name != 'articles':
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()

def create_social_post_entries(article_id: int, medium_url: str) -> int:
    """
    Create social post entries for all social accounts in the social_accounts sheet
    for the given article
    
    Args:
        article_id: The ID of the article
        medium_url: The URL of the Medium post
        
    Returns:
        int: The number of social post entries created
    """
    excel_data, file_id = download_excel_from_drive()
    
    if 'social_accounts' not in excel_data or 'social_posts' not in excel_data:
        raise ValueError("Excel file must contain 'social_accounts' and 'social_posts' sheets.")
    
    social_accounts_df = excel_data['social_accounts']
    social_posts_df = excel_data['social_posts']
    
    # Check if necessary columns exist
    required_columns = ['id', 'employee_name', 'platform']
    for col in required_columns:
        if col not in social_accounts_df.columns:
            raise ValueError(f"Social accounts sheet missing required column: {col}")
    
    # Get the next available ID for social posts
    next_id = get_next_social_post_id()
    
    # Create new entries for all social accounts
    new_posts = []
    for _, account in social_accounts_df.iterrows():
        new_post = {
            "id": next_id,
            "employee_name": account["employee_name"],
            "platform": account["platform"],
            "article_id": article_id,
            "posted": False,
            "post_date": "",
            "post_url": ""
        }
        new_posts.append(new_post)
        next_id += 1
    
    # Add the new posts to the dataframe
    if new_posts:
        new_posts_df = pd.DataFrame(new_posts)
        social_posts_df = pd.concat([social_posts_df, new_posts_df], ignore_index=True)
    
    # Save and upload
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        # Write all sheets
        for sheet_name, df in excel_data.items():
            if sheet_name != 'social_posts':
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        # Write the updated social_posts sheet
        social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)
    
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    
    return len(new_posts)

def publish_medium(filename: str | None = None):
    """Publish unpublished draft(s) to Medium.

    Args:
        filename: If provided, publish only that file; otherwise publish **all** files
                  in the *articles* sheet where ``posted_medium`` is ``False``.

    Returns:
        • When *filename* supplied → dict with publish details for that single draft.
        • When *filename* omitted  → list[dict] of the above for every published draft.
    """

    # 1) Identify unpublished drafts via the articles sheet
    unpublished_files = get_unpublished_filenames()
    if not unpublished_files:
        print("No drafts pending for Medium.")
        return {"status": "nothing_to_publish"}

    # If a specific filename is requested validate it, else publish all
    if filename:
        if filename not in unpublished_files:
            print(f"[ERROR] Requested filename '{filename}' not found in unpublished drafts.")
            return {"status": "invalid_selection"}
        files_to_publish = [filename]
        print(f"[INFO] User-selected draft: {filename}")
    else:
        # Default behaviour: publish only the FIRST unpublished draft
        chosen_file = unpublished_files[0]
        files_to_publish = [chosen_file]
        print(f"[INFO] Will publish first draft: {chosen_file}")

    results: list[dict] = []

    for chosen_file in files_to_publish:
        print(f"\n[INFO] Publishing: {chosen_file}")

        # Build Drive path for the markdown draft
        file_path = path_extractor(chosen_file, 'medium')

        if not DRIVE_FOLDER_ID:
            raise RuntimeError("DRIVE_FOLDER_ID env var is missing")

        raw = retrieve_file_from_drive_path(file_path, DRIVE_FOLDER_ID)
        text = raw.decode('utf-8').splitlines()

        # -------- Prepare title & body --------
        title = ""
        for line in text:
            if line.strip():
                title = line.lstrip('# ').strip().replace("**", "")
                break

        body_txt = "\n".join(text[1:]).replace("**", "")

        # -------- Post using Playwright --------
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            ctx     = browser.new_context()
            page    = ctx.new_page()

            login_medium(page)
            print("✅ Logged in.")
            article_url = post_to_medium(page, title, body_txt)
            medium_url  = shorten_url(article_url)
            print(f"✅ Published: {title!r}")

            # Update the article entry in Excel
            updates = {
                "posted_medium": True,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "medium_url": medium_url,
            }
            update_article_entry(filename=chosen_file, updates=updates)
            print("✅ Articles sheet updated")

            # Create social-post tasks
            article_id = get_article_id_by_filename(chosen_file)
            if article_id is not None:
                num_posts = create_social_post_entries(article_id, medium_url)
                print(f"✅ Created {num_posts} social post entries")
            else:
                print("❌ Failed to find article ID, social post entries not created")

            ctx.close()
            browser.close()

        results.append({
            "status": "published",
            "file": chosen_file,
            "title": title,
            "url": medium_url,
        })

    # ------ Return results ------
    if len(results) == 1:
        return results[0]
    return results

def main():
    print(get_unpublished_filenames())

if __name__ == "__main__":
    main()

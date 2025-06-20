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

# Load environment variables
load_dotenv()

# ---------- Configuration ----------
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
DRIVE_SCOPES             = os.getenv("DRIVE_SCOPE")
FOLDER_ID            = os.getenv("DRIVE_FOLDER_ID")
GOOGLE_EMAIL         = os.getenv("GOOGLE_EMAIL")
GOOGLE_PASSWORD      = os.getenv("GOOGLE_PASSWORD")

DATABASE                = os.getenv("BLOG_CONTENT_DATABASE")
EXCEL_NAME              = os.getenv("EXCEL_NAME")
EXCEL_PATH              = os.path.join(DATABASE, EXCEL_NAME)

creds                = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=DRIVE_SCOPES)
drive                = build('drive', 'v3', credentials=creds)
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
        result = drive.files().list(q=query, fields="files(id, name)").execute()
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
    query = f"name = '{EXCEL_NAME}' and '{FOLDER_ID}' in parents"
    result = drive.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    if not files:
        raise FileNotFoundError("Excel file not found on Drive.")

    file_id = files[0]["id"]
    request = drive.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    df = pd.read_excel(fh)
    return df, file_id

def get_unpublished_filenames():
    df, _ = download_excel_from_drive()
    if "posted_on_medium" not in df.columns or "filename" not in df.columns:
        raise ValueError("Excel must contain 'posted_on_medium' and 'filename' columns.")
    return df[df["posted_on_medium"] == False]["filename"].tolist()

def shorten_url(url):
    response = requests.get(f"http://tinyurl.com/api-create.php?url={url}")
    return response.text.strip()

def login_medium(page):
    # 1) Go to Medium’s mobile sign-in
    page.goto("https://medium.com/m/signin", wait_until="domcontentloaded")
    
    # 2) (Optional) dismiss cookie banner
    try:
        page.click("button:has-text('Accept all')", timeout=5_000)
        page.wait_for_timeout(1_000)
    except PlaywrightTimeoutError:
        pass

    # 3) Click “Sign in with Google”
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
    drive.files().update(fileId=file_id, media_body=media).execute()

def main():

    # 2) Find target folder
    unpublished_files = get_unpublished_filenames()
    print("Files not yet posted to Medium:")
    for idx, name in enumerate(unpublished_files, 1):
        print(f"{idx}. {name}")

    choice = int(input("Enter the number of the file to choose: ").strip())
    if 1 <= choice <= len(unpublished_files):
        chosen_file = unpublished_files[choice - 1]
        print(f"You chose: {chosen_file}")
    else:
        print("Invalid selection.")

    file_path = path_extractor(chosen_file, 'medium')

    raw = retrieve_file_from_drive_path(file_path, FOLDER_ID)
    text = raw.decode('utf-8').splitlines()

    # 6) Extract title (first non-empty, strip leading “# ”, then remove any “**”)
    title = ""
    for line in text:
        if line.strip():
            title = line.lstrip('# ').strip().replace("**", "")
            break

    # 7) Build body MD (skip the first line) and strip all “**”
    body_txt = "\n".join(text[1:]).replace("**", "")

    # 8) Launch Playwright & run
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx     = browser.new_context()
        page    = ctx.new_page()

        login_medium(page)
        print("✅ Logged in.")
        article_url =  post_to_medium(page, title, body_txt)
        # article_url = 'https://medium.com/@shresth.kansal/unlocking-business-opportunities-with-smart-contracts-a-guide-for-entrepreneurs-d2815c961229'
        medium_url = shorten_url(article_url)
        print(f"✅ Published: {title!r}")

        # --------------- new: capture URL & log to Excel ---------------
        
        print(f"This is the URL:{article_url}")
        updates = {
            "posted_on_medium": True,
            "medium_date": datetime.now().strftime("%Y-%m-%d"),
            "medium_url": medium_url,
        }
        update_existing_entry(filename = chosen_file, updates = updates)
        print(f"✅ Excel Updated")


        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()

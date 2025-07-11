#!/usr/bin/env python3

import os
import json
import re
import io
import openai
import pandas as pd
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload
from dotenv import load_dotenv
import random
from typing import Optional, Dict, List, Any, Tuple
from core.credentials import google, global_cfg

gcreds      = google()
global_cfg  = global_cfg()

load_dotenv()

# ---------- Helper Functions ----------

def getenv_required(name: str) -> str:
    v: Optional[str] = os.getenv(name)
    if not v:                         # catches None and empty string
        raise RuntimeError(f"{name} is not set")
    return v

# ---------- Global Configuration ----------
openai.api_key          = os.getenv("OPENAI_API_KEY")
KEYWORDS_FILE           = global_cfg["keywords_file"]
DATABASE                = global_cfg["blog_content_database"]
EXCEL_NAME              = global_cfg["excel_name"]
DEMO_LINK               = global_cfg["demo_link"]
EXCEL_PATH              = os.path.join(DATABASE, EXCEL_NAME)

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

DENSITY_MIN    = 0.02
DENSITY_MAX    = 0.03
WORD_COUNT_MIN = 400
WORD_COUNT_MAX = 500

# ---------- Drive Configuration ----------

SERVICE_ACCOUNT_FILE    = gcreds["service_account_json"]
DRIVE_FOLDER_ID         = gcreds["drive_folder_id"]
DRIVE_SCOPE             = [gcreds["drive_scope"]]
SHARED_DRIVE_ID         = gcreds["shared_drive_id"]

DRIVE_KWARGS: dict[str, object] = {"supportsAllDrives": True}
LIST_KWARGS: dict[str, object] = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"})

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=DRIVE_SCOPE
)
drive = build("drive", "v3", credentials=creds)
today = datetime.now().strftime("%d-%m-%y")  # e.g. "16-Jun-2025"
excel_date = datetime.now().strftime("%Y-%m-%d")
date_slug = datetime.now().strftime("%d-%m-%y")

# ---------- Helper Functions ----------

DEBUG = True

def log(msg: str):
    if DEBUG:
        print(f"{msg}")

def generate_filename(kw: str, platform: str = "", ext: str = ".txt") -> str:
    kw_slug = kw.replace(" ", "-").lower()
    platform_ = '' if platform == '' else platform+'_'
    return f"{platform_}{date_slug}_{kw_slug}{ext}"

def load_top_keywords(n=3):
    """Return up to *n* unused keywords ordered as they appear in the JSON file.

    A keyword is considered unused when its object either lacks the "used" key
    or that key is set to False. If fewer than *n* unused keywords exist we
    return as many as available."""

    with open(str(KEYWORDS_FILE)) as f:
        data = json.load(f)

    unused = [e for e in data if not e.get("used")]
    picked = unused[:n]
    keywords = [e["keyword"] for e in picked]
    log(f"Loaded {len(keywords)} unused keyword(s): {keywords}")
    return keywords

def _mark_keyword_used(keyword: str):
    """Set used:true for *keyword* in the keywords JSON file."""
    try:
        with open(str(KEYWORDS_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for entry in data:
            if entry.get("keyword") == keyword:
                if not entry.get("used"):
                    entry["used"] = True
                    changed = True
                break
        if changed:
            with open(str(KEYWORDS_FILE), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log(f"Marked keyword '{keyword}' as used in keywords.json")
    except Exception as e:
        print(f"[WARN] Failed to mark keyword '{keyword}' as used: {e}")

def keyword_density(text: str, keyword: str) -> float:
    words = re.findall(r"\\w+", text.lower())
    count = len(re.findall(re.escape(keyword.lower()), text.lower()))
    return count / len(words) if words else 0

def build_prompt(keyword: str) -> str:
    return (
        f"Write a 400-500 word article for entrepreneurs on \"{keyword}\". "
        f"""Use the exact phrase \"{keyword}\" at 2-3% density. "
        Do not use any formatting like ** or __. Do not prefix the title with 'Title:'. 
        Structure the piece with: 
        • A Title
        • An intro (100-150 words) setting the scene and pain points
        • 4-6 sections (headings, ~100-180 words each) each with:\n"
            - An actionable tip tied to "{keyword}"\n"
            - How to use Legitt AI to implement that tip\n"

        • A mid-body CTA: Try Legitt AI in your free demo today: https://legittai.com/demo
        • A conclusion with a summary
        Don't explicitly write Title: or Section 1:
        Use short paragraphs, no bullets paragraph style, no lists

        """
    )

def generate_blog(prompt):
    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert blog writer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=700
    )
    log("Blog article generated via OpenAI")
    return str(resp.choices[0].message.content).strip()

def adjust_for_density(text: str, keyword: str, prompt: str) -> str:
    dens = keyword_density(text, keyword)
    if dens < DENSITY_MIN or dens > DENSITY_MAX:
        feedback = (
            f"The density of '{keyword}' is {dens*100:.2f}%. Please adjust to 2-3%."
        )
        return generate_blog(prompt + "\n\n" + feedback)
    return text

def ensure_drive_folder(name: str, parent_id: str = '') -> str:
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    resp = drive.files().list(q=query, fields="files(id, name)", **LIST_KWARGS).execute()
    files = resp.get("files", [])
    if files:
        log(f"Found existing Drive folder '{name}' (id={files[0]['id']})")
        return files[0]["id"]
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id] # type: ignore
    folder = drive.files().create(body=metadata, fields="id", **DRIVE_KWARGS).execute()
    log(f"Created Drive folder '{name}' (id={folder['id']}) under parent {parent_id}")
    return folder["id"]

def upload_to_drive(file_path: str, folder_id: str):
    file_metadata = {"name": os.path.basename(file_path), "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype="text/plain")
    file = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
        **DRIVE_KWARGS
    ).execute()
    log(f"Uploaded '{file_path}' to Drive folder {folder_id} (file id={file['id']})")
    return file["id"]

def generate_summary(text: str, platform: str) -> str:
    demo_link = DEMO_LINK
    medium_link = "{{medium_link}}"    
    templates = [
    f"{{hook}}? {{feature}}. Check out a live preview at {demo_link}! Read all about it → {medium_link}",
    f"🚀 {{hook}} ➡️ {{feature}} (live demo: {demo_link}) 📖 Details: {medium_link}",
    f"Full breakdown here: {medium_link}. {{hook}} and discover how {{feature}}. Try it now: {demo_link}",
    f"{{hook}} {{feature}}! (see it live: {demo_link}) Dive deeper: {medium_link}",
    f"{{hook}}. {{feature}}. Experience it yourself: {demo_link} — more insights at {medium_link}",
    f"{{hook}}—{{feature}}—live demo {demo_link}—full story {medium_link}",
    f"Try a live demo: {demo_link}. {{hook}} {{feature}}. Learn more here: {medium_link}",
    f"{{hook}} {{feature}} (details: {medium_link}). See it in action at {demo_link}",
    f"#Contracts {{hook}}! {{feature}}. Learn how → {medium_link}. See it live: {demo_link}",
    f"{{hook}}: {{feature}} | Demo → {demo_link} | Read more → {medium_link}",
    f"Discover how {{feature}} 🤖 in our latest piece {medium_link}, then try a demo at {demo_link}",
    f"1️⃣ {{hook}} 2️⃣ {{feature}} 3️⃣ See for yourself: {demo_link} • Full read: {medium_link}"]

    if platform == 'twitter':
        template = random.choice(templates)
        prompt = (
            f"Generate a tweet (≤270 chars) by filling in:\n"
            f"  hook: your opening question or statement\n"
            f"  feature: the core benefit or capability\n"
            f"  acceptable names for the product are Legitt.AI, Legitt AI, LegittAI.com that's it\n"
            f"  demo: {demo_link}\n"
            f"  article: {medium_link}\n\n"
            f"Template:\n{template}"
    )
        
    elif platform == 'linkedin':
        prompt = f"""Write a LinkedIn post summarizing the article for professionals. No formatting like bold or italics. Include {demo_link} naturally mid post in a sentence, not at the end. Mention the medium article at the end: use phrasing semantically similar to 'For a deeper dive into this topic, read more here' {medium_link}.
            {text}"""

    else:
        raise ValueError("Unsupported platform")

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens = 500 if platform == 'linkedin' else 200,
        temperature=0.7,
    )
    raw_text = str(response.choices[0].message.content).strip()

    # --- safety net: ensure placeholder is always the exact expected string ---
    fixed_text = (
        raw_text
        .replace("({article})", "{{medium_link}}")
        .replace("{article}", "{{medium_link}}")
        .replace("{{article}}", "{{medium_link}}")
    )

    log(f"Generated {platform} summary")
    return fixed_text

def download_excel_from_drive() -> Tuple[Dict[str, pd.DataFrame], str]:
    """
    Download the Excel file from Drive and return a dictionary of dataframes,
    one for each sheet, and the file ID.
    """
    # Check if the Excel file exists on Drive
    query = f"name = '{EXCEL_NAME}' and '{DRIVE_FOLDER_ID}' in parents"
    result = drive.files().list(q=query, fields="files(id, name)", **LIST_KWARGS).execute()
    files = result.get("files", [])

    if files:
        # Download the existing Excel file
        file_id = files[0]["id"]
        request = drive.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        # Read all sheets into a dictionary of dataframes
        excel_data = pd.read_excel(fh, sheet_name=None)
        return excel_data, file_id
    else:
        # Create a new Excel file with the three-sheet structure
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

        # Create dictionary of dataframes
        excel_data = {
            'articles': articles_df,
            'social_accounts': social_accounts_df,
            'social_posts': social_posts_df
        }
        
        return excel_data, ""  # Empty file_id indicates new file needs to be created

def get_next_article_id() -> int:
    """Get the next available ID for articles"""
    excel_data, _ = download_excel_from_drive()
    
    if 'articles' not in excel_data or excel_data['articles'].empty:
        return 1
    
    if 'id' not in excel_data['articles'].columns:
        return 1
    
    return int(excel_data['articles']['id'].max() + 1)

def update_excel(article_metadata: dict):
    """
    Update the Excel file with new article information.
    
    Args:
        article_metadata: Dictionary containing article information like filename, date, keyword
    """
    excel_data, file_id = download_excel_from_drive()
    
    # Check if we need to create a new Excel file
    if not file_id:
        file_id = ""  # Ensure it's a string for later checks
    
    # Ensure the 'articles' sheet exists
    if 'articles' not in excel_data:
        # Create a DataFrame with empty data but with the correct column structure
        excel_data['articles'] = pd.DataFrame({col: [] for col in ARTICLES_COLUMNS})
    
    # Get the next article ID
    next_id = get_next_article_id()
    
    # Create the article record
    article_record = {
        "id": next_id,
        "filename": article_metadata.get("filename", ""),
        "date": article_metadata.get("date", excel_date),
        "posted_medium": article_metadata.get("posted_medium", False),
        "keyword": article_metadata.get("keyword", ""),
        "medium_url": article_metadata.get("medium_url", "")
    }
    
    # Add the new article to the articles sheet
    articles_df = excel_data['articles']
    articles_df = pd.concat([articles_df, pd.DataFrame([article_record])], ignore_index=True)
    excel_data['articles'] = articles_df
    
    # Write all sheets to the Excel file
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        for sheet_name, df in excel_data.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    # Upload the updated Excel file to Drive
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if file_id:
        drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
        log("Excel file updated on Drive")
    else:
        file_metadata = {"name": EXCEL_NAME, "parents": [DRIVE_FOLDER_ID]}
        new_file = drive.files().create(body=file_metadata, media_body=media, fields="id", **DRIVE_KWARGS).execute()
        log(f"New Excel file created on Drive with ID: {new_file['id']}")
    
    return next_id  # Return the article ID for reference

def create_content(keywords: list[str] | None = None) -> dict:
    # --- Health check: verify Google Drive API connectivity ---
    try:
        drive.about().get(fields="user").execute()
        print("[INFO] Google Drive API connection verified.")
    except Exception as e:
        print(f"[ERROR] Google Drive API connection failed: {e}")
        raise

    log("Starting content generation run")
    if keywords is None or not keywords:
        keywords = load_top_keywords(n=1)  # default behaviour

    # ensure we have a list (even if caller passed a single string)
    if isinstance(keywords, str):
        keywords = [keywords]

    root_folder_id = ensure_drive_folder(today, parent_id=DRIVE_FOLDER_ID)
    folder_ids = {
        p: ensure_drive_folder(p, parent_id=root_folder_id)
        for p in ["medium", "twitter", "linkedin"]
    }

    summaries: list[dict] = []

    for kw in keywords:
        log(f"Processing keyword '{kw}'")
        prompt = build_prompt(kw)
        blog = generate_blog(prompt)
        blog = adjust_for_density(blog, kw, prompt)
        fname = generate_filename(kw, platform="medium")
        fpath = os.path.join(DATABASE, "medium", fname)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(blog)
        upload_to_drive(fpath, folder_ids["medium"])
        log(f"Uploaded blog article for '{kw}'")

        for platform in ["twitter", "linkedin"]:
            summary_text = generate_summary(blog, platform)
            sum_fname = generate_filename(kw, platform=platform)
            sum_path = os.path.join(DATABASE, platform, sum_fname)
            os.makedirs(os.path.dirname(sum_path), exist_ok=True)
            with open(sum_path, "w", encoding="utf-8") as f:
                f.write(summary_text)
            upload_to_drive(sum_path, folder_ids[platform])
            log(f"Uploaded {platform} summary for '{kw}'")

        # Update Excel with the new article information
        article_id = update_excel({
            "filename": generate_filename(kw, platform=""),
            "date": excel_date,
            "posted_medium": False,
            "keyword": kw,
        })
        log(f"Article recorded with ID {article_id} for '{kw}' in Excel")

        # Mark keyword as used in keywords.json so UI hides/flags it next time
        _mark_keyword_used(kw)

        summaries.append({
            "article_id": article_id,
            "keyword": kw,
            "medium_file": fname,
            "twitter_file": generate_filename(kw, platform="twitter"),
            "linkedin_file": generate_filename(kw, platform="linkedin"),
        })

    log(f"status: success, keywords_processed: {len(summaries)}, details: {summaries}")
    return {
        "status": "success",
        "keywords_processed": len(summaries),
        "details": summaries,
    }

def main():
    create_content()

if __name__ == "__main__":
    main()


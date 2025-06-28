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
from agent_keyword_generator import generate_keys

# generate_keys()

load_dotenv()

# === CONFIGURATION ===
openai.api_key          = os.getenv("OPENAI_API_KEY")
KEYWORDS_FILE           = os.getenv("KEYWORDS_FILE")

SERVICE_ACCOUNT_FILE    = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
DRIVE_FOLDER_ID         = os.getenv("DRIVE_FOLDER_ID")
DRIVE_SCOPE             = ['https://www.googleapis.com/auth/drive']

DATABASE                = os.getenv("BLOG_CONTENT_DATABASE")
EXCEL_NAME              = os.getenv("EXCEL_NAME")
EXCEL_PATH              = os.path.join(DATABASE, EXCEL_NAME)

DEMO_LINK               = os.getenv("DEMO_LINK")

DENSITY_MIN    = 0.02
DENSITY_MAX    = 0.03
WORD_COUNT_MIN = 400
WORD_COUNT_MAX = 500

SHARED_DRIVE_ID        = os.getenv("SHARED_DRIVE_ID")
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

# === HELPERS ===

DEBUG = True

def log(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}")

def generate_filename(kw: str, platform: str = "", ext: str = ".txt") -> str:
    kw_slug = kw.replace(" ", "-").lower()
    platform_ = '' if platform == '' else platform+'_'
    return f"{platform_}{date_slug}_{kw_slug}{ext}"

def load_top_keywords(n=3):
    with open(KEYWORDS_FILE) as f:
        data = json.load(f)
    keywords = [entry["keyword"] for entry in data[:n]]
    log(f"Loaded top {n} keywords: {keywords}")
    return keywords

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
    return resp.choices[0].message.content.strip()

def adjust_for_density(text: str, keyword: str, prompt: str) -> str:
    dens = keyword_density(text, keyword)
    if dens < DENSITY_MIN or dens > DENSITY_MAX:
        feedback = (
            f"The density of '{keyword}' is {dens*100:.2f}%. Please adjust to 2-3%."
        )
        return generate_blog(prompt + "\n\n" + feedback)
    return text

def ensure_drive_folder(name: str, parent_id: str = None) -> str:
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
        metadata["parents"] = [parent_id]
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
    "{hook}? {feature}. Check out a live preview at {demo}! Read all about it → {article}",
    "🚀 {hook} ➡️ {feature} (live demo: {demo}) 📖 Details: {article}",
    "Full breakdown here: {article}. {hook} and discover how {feature}. Try it now: {demo}",
    "{hook} {feature}! (see it live: {demo}) Dive deeper: {article}",
    "{hook}. {feature}. Experience it yourself: {demo} — more insights at {article}",
    "{hook}—{feature}—live demo {demo}—full story {article}",
    "Try a live demo: {demo}. {hook} {feature}. Learn more here: {article}",
    "{hook} {feature} (details: {article}). See it in action at {demo}",
    "#Contracts {hook}! {feature}. Learn how → {article}. See it live: {demo}",
    "{hook}: {feature} | Demo → {demo} | Read more → {article}",
    "Discover how {feature} 🤖 in our latest piece ({article}), then try a demo at {demo}",
    "1️⃣ {hook} 2️⃣ {feature} 3️⃣ See for yourself: {demo} • Full read: {article}"]

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
    log(f"Generated {platform} summary")
    return response.choices[0].message.content.strip()

def update_excel(metadata: dict):
    query = f"name = '{EXCEL_NAME}' and '{DRIVE_FOLDER_ID}' in parents"
    result = drive.files().list(q=query, fields="files(id, name)", **LIST_KWARGS).execute()
    files = result.get("files", [])

    if files:
        file_id = files[0]["id"]
        request = drive.files().get_media(fileId=file_id)
        with open(EXCEL_PATH, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()

        df = pd.read_excel(EXCEL_PATH)
    else:
        df = pd.DataFrame(columns=["filename", "date_generated", "posted_on_medium", "posted_on_twitter", "posted_on_linkedin"b])
        file_id = None

    df = pd.concat([df, pd.DataFrame([metadata])], ignore_index=True)
    df.to_excel(EXCEL_PATH, index=False)

    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if file_id:
        drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    else:
        file_metadata = {"name": EXCEL_NAME, "parents": [DRIVE_FOLDER_ID]}
        drive.files().create(body=file_metadata, media_body=media, fields="id", **DRIVE_KWARGS).execute()
    log("Excel file updated on Drive")

def main():
    # --- Health check: verify Google Drive API connectivity ---
    try:
        drive.about().get(fields="user").execute()
        print("[INFO] Google Drive API connection verified.")
    except Exception as e:
        print(f"[ERROR] Google Drive API connection failed: {e}")
        raise

    log("Starting content generation run")
    keywords = load_top_keywords(n=3)
    root_folder_id = ensure_drive_folder(today, parent_id=DRIVE_FOLDER_ID)
    folder_ids = {
        p: ensure_drive_folder(p, parent_id=root_folder_id)
        for p in ["medium", "twitter", "linkedin"]
    }

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
            summary = generate_summary(blog, platform)
            sum_fname = generate_filename(kw, platform=platform)
            sum_path = os.path.join(DATABASE, platform, sum_fname)
            os.makedirs(os.path.dirname(sum_path), exist_ok=True)
            with open(sum_path, "w", encoding="utf-8") as f:
                f.write(summary)
            upload_to_drive(sum_path, folder_ids[platform])
            log(f"Uploaded {platform} summary for '{kw}'")

        update_excel({
            "filename": generate_filename(kw, platform=""),
            "date_generated": excel_date,
            "posted_on_medium": False,
            "posted_on_twitter": False,
            "posted_on_linkedin": False,
        })
        log(f"Metadata recorded for '{kw}' in Excel")

if __name__ == "__main__":
    main()


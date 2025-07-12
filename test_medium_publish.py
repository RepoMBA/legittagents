#!/usr/bin/env python3
"""
Test Script - Medium Publishing

This script simulates publishing an article to Medium and demonstrates
how the system automatically creates entries in the social_posts sheet
when an article is marked as published on Medium.
"""

import os
import pandas as pd
import time
import random
from datetime import datetime
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.discovery import build
from google.oauth2 import service_account
import io

from core.credentials import global_cfg, google

# Get configuration
cfg = global_cfg()
gcreds = google()
DATABASE = cfg["blog_content_database"]
EXCEL_NAME = cfg["excel_name"]
EXCEL_PATH = os.path.join(DATABASE, EXCEL_NAME)

# Google Drive setup
SERVICE_ACCOUNT_FILE = gcreds["service_account_json"]
DRIVE_SCOPE = [gcreds["drive_scope"]]
FOLDER_ID = gcreds["drive_folder_id"]
SHARED_DRIVE_ID = gcreds["shared_drive_id"]

DRIVE_KWARGS = {"supportsAllDrives": True}
LIST_KWARGS = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
if SHARED_DRIVE_ID:
    LIST_KWARGS.update({"driveId": SHARED_DRIVE_ID, "corpora": "drive"}) # type: ignore

# Initialize Drive API client
drive_creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=DRIVE_SCOPE,
)
drive = build("drive", "v3", credentials=drive_creds)

def download_excel():
    """Download the Excel file and return the sheets."""
    # Find Excel file
    query = f"name = '{EXCEL_NAME}' and '{FOLDER_ID}' in parents"
    res = drive.files().list(q=query, fields="files(id,name)", **LIST_KWARGS).execute()
    files = res.get("files", [])
    if not files:
        raise FileNotFoundError(f"Excel file not found on Drive: {EXCEL_NAME}")
    
    file_id = files[0]["id"]
    request = drive.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    
    # Read all sheets
    xl = pd.ExcelFile(fh)
    sheet_names = xl.sheet_names
    
    result = {'file_id': file_id}
    
    if 'articles' in sheet_names:
        result['articles'] = pd.read_excel(fh, sheet_name='articles', dtype={'medium_url': str})
    
    if 'social_accounts' in sheet_names:
        result['social_accounts'] = pd.read_excel(fh, sheet_name='social_accounts')
    
    if 'social_posts' in sheet_names:
        result['social_posts'] = pd.read_excel(fh, sheet_name='social_posts', dtype={'post_url': str})
        
    return result

def add_test_article():
    """Add a test article and return its ID."""
    # Download current Excel
    excel_data = download_excel()
    file_id = excel_data['file_id']
    articles_df = excel_data['articles']
    social_accounts_df = excel_data['social_accounts']
    social_posts_df = excel_data['social_posts']
    
    # Create test article filename
    timestamp = int(time.time())
    test_filename = f"{timestamp}_medium_test_article.md"
    print(f"Adding test article: {test_filename}")
    
    # Generate sequential ID
    new_id = 1
    if not articles_df.empty and 'id' in articles_df.columns and len(articles_df) > 0:
        new_id = int(articles_df["id"].max() + 1)
    
    # Create new article entry
    new_article = {
        'id': new_id,
        'filename': test_filename,
        'date': pd.Timestamp.now().strftime("%Y-%m-%d"),
        'posted_medium': False,
        'keyword': "test medium publishing",
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
    
    return new_id, test_filename

# excel_data = download_excel()
# file_id = excel_data['file_id']
# articles_df = excel_data['articles']
# social_accounts_df = excel_data['social_accounts']
# social_posts_df = excel_data['social_posts']
# print(articles_df.columns)
# print(social_accounts_df.columns)
# print(social_posts_df.columns)
# print(articles_df.head())
# print(social_accounts_df.head())
# print(social_posts_df.head())
# print(articles_df.iloc[0])
# print(social_accounts_df.iloc[0])
# print(social_posts_df.iloc[0])
def simulate_medium_publish(article_id, filename):
    """Simulate publishing an article to Medium."""
    # Download current Excel
    excel_data = download_excel()
    file_id = excel_data['file_id']
    articles_df = excel_data['articles']
    social_accounts_df = excel_data['social_accounts']
    social_posts_df = excel_data['social_posts']


    # Find the article
    article_mask = articles_df['id'] == article_id
    if not article_mask.any():
        print(f"❌ Error: Article with ID {article_id} not found!")
        return False
    
    # Generate a fake Medium URL
    medium_url = f"https://medium.com/@test-user/{filename.replace('_', '-').replace('.md', '')}-{random.randint(1000, 9999)}"
    
    # Count social accounts before update
    print(f"\nBefore Medium publish:")
    print(f"  - Number of social accounts: {len(social_accounts_df)}")
    print(f"  - Number of social posts: {len(social_posts_df)}")
    print(f"  - Social account columns: {list(social_accounts_df.columns)}")
    print(f"  - Social posts columns: {list(social_posts_df.columns)}")
    
    # Update the article to mark as published
    articles_df.loc[article_mask, 'posted_medium'] = True
    articles_df.loc[article_mask, 'medium_url'] = medium_url
    articles_df.loc[article_mask, 'date'] = datetime.now().strftime("%Y-%m-%d")
    
    # Get the next available ID for social posts
    next_id = 1
    if not social_posts_df.empty and 'id' in social_posts_df.columns and len(social_posts_df) > 0:
        next_id = int(social_posts_df['id'].max()) + 1 if len(social_posts_df) > 0 else 1
    
    # For each social account, create a pending post
    new_posts = []
    for _, account in social_accounts_df.iterrows():
        new_posts.append({
            'id': next_id,
            'employee_name': account['employee_name'],
            'platform': account['platform'],
            'article_id': article_id,
            'posted': False,
            'post_date': '',
            'post_url': ''
        })
        next_id += 1
    
    # Add new posts to dataframe
    if new_posts:
        social_posts_df = pd.concat([social_posts_df, pd.DataFrame(new_posts)], ignore_index=True)
    
    # Save all sheets
    with pd.ExcelWriter(EXCEL_PATH, engine='openpyxl') as writer:
        articles_df.to_excel(writer, sheet_name='articles', index=False)
        social_accounts_df.to_excel(writer, sheet_name='social_accounts', index=False)
        social_posts_df.to_excel(writer, sheet_name='social_posts', index=False)
    
    # Upload the updated file
    media = MediaFileUpload(EXCEL_PATH, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    drive.files().update(fileId=file_id, media_body=media, **DRIVE_KWARGS).execute()
    
    print(f"\n✅ Successfully simulated publishing to Medium:")
    print(f"  - URL: {medium_url}")
    
    # Download again to verify
    excel_data = download_excel()
    social_posts_df = excel_data['social_posts']
    
    # Count social posts after update
    article_posts = social_posts_df[social_posts_df['article_id'] == article_id]
    
    print(f"\nAfter Medium publish:")
    print(f"  - Number of social accounts: {len(social_accounts_df)}")
    print(f"  - Number of social posts: {len(social_posts_df)}")
    print(f"  - Number of posts for this article: {len(article_posts)}")
    
    # Print details of the social posts for this article
    if not article_posts.empty:
        print("\nSocial posts created for this article:")
        for idx, post in article_posts.iterrows():
            print(f"  - Post ID: {post['id']}")
            print(f"    Platform: {post['platform']}")
            print(f"    Employee: {post['employee_name']}")
            print(f"    Posted: {post['posted']}")
            print()
    
    return True

def main():
    # Add a test article
    article_id, filename = add_test_article()
    print(f"Added article with ID: {article_id}")
    
    # Simulate publishing to Medium
    simulate_medium_publish(article_id, filename)

if __name__ == "__main__":
    main() 
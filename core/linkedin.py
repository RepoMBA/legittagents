# Standard libs
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

# External deps
from dotenv import load_dotenv
import requests

from core.credentials import global_cfg, user as _user_creds

global_cfg = global_cfg()

# Load environment variables
load_dotenv()

# ---------- Global Configuration ----------

DATABASE: str = global_cfg["blog_content_database"]
EXCEL_NAME: str = global_cfg["excel_name"]

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

def post_linkedin() -> dict:
    # Import needed functions here to avoid circular import
    from Utils.google_drive import (
        update_existing_entry,
        retrieve_file_from_drive_path,
        path_extractor,
        get_unpublished_filenames,
        FOLDER_ID
    )
    
    # 2) Find target folder
    platform = 'linkedin'

    # ------------------------------------------------------------------
    # Restrict the LinkedIn publishing run to the *active* user so that
    # Excel updates map to the correct row.
    # ------------------------------------------------------------------
    active_user: Optional[str] = os.getenv("ACTIVE_USER")
    unpublished_files = get_unpublished_filenames(platform, employee_name=active_user)
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
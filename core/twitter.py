import requests
from typing import List, Dict, Any, Optional
import os
from datetime import datetime

from dotenv import load_dotenv

from core.credentials import global_cfg, user as _user_creds

global_cfg = global_cfg()

def getenv_required(name: str) -> str:
    v: Optional[str] = os.getenv(name)
    if not v:                         # catches None and empty string
        raise RuntimeError(f"{name} is not set")
    return v

load_dotenv()

# ---------- Global Configuration ----------
DATABASE: str = global_cfg["blog_content_database"]
EXCEL_NAME: str = global_cfg["excel_name"]

# ---------- Twitter credentials (per ACTIVE_USER) ----------
_tw_creds = _user_creds().get("twitter", {})
_BEARER_TOKEN: Optional[str] = _tw_creds.get("access_token")
_SCREEN_NAME: Optional[str] = _tw_creds.get("screen_name")

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

def post_twitter(user_id) -> dict:
    # Import needed functions here to avoid circular import
    from Utils.google_drive import (
        update_existing_entry,
        retrieve_file_from_drive_path,
        path_extractor,
        get_unpublished_filenames as get_unpublished_entries,
        FOLDER_ID
    )
    
    platform = "twitter"
    print("[INFO] Starting Twitter publishing run…")

    # ------------------------------------------------------------------
    # Resolve credentials for the *current* ACTIVE_USER (env variable may
    # be switched at runtime so we cannot rely on the values captured at
    # import-time).
    # ------------------------------------------------------------------
    active_user: Optional[str] = os.getenv("ACTIVE_USER")
    try:
        user_creds = _user_creds(user_id) if user_id else _user_creds(active_user)
    except KeyError:
        print(f"[ERROR] Unknown user '{active_user}'. Ensure ACTIVE_USER env var is set correctly.")
        return {"status": "error", "error": "unknown_user"}

    tw_creds = user_creds.get("twitter", {})
    bearer_token: Optional[str] = tw_creds.get("access_token")
    screen_name:  Optional[str] = tw_creds.get("screen_name")

    if not bearer_token or not screen_name:
        print("[ERROR] Missing Twitter access token or screen name in credentials JSON for the active user")
        return {"status": "error", "error": "missing_credentials"}

    # ------------------------------------------------------------------
    # Restrict publishing run to the active user only so updates are
    # applied to the correct social_posts rows.
    # ------------------------------------------------------------------
    entries = get_unpublished_entries(platform, employee_name=active_user)

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
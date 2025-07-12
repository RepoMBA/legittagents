#!/usr/bin/env python3
"""
Simulate Medium Publish
----------------------

This script emulates what `content_publisher --run publish_medium` (or the
Playwright-driven path in `core.medium.publish_medium`) does – *without* opening
any browser.  It:

1. Downloads the tracking Excel from Drive.
2. Finds the first article whose **posted_medium == False**.
3. Flips that flag to **True**, adds a dummy Medium URL, and updates the date.
4. Calls the existing helper that creates social-post tasks so the
   `social_posts` sheet is populated for every social account.

Run:
    python simulate_medium_publish.py
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Optional

from core.medium import (
    download_excel_from_drive,
    update_article_entry,
    get_article_id_by_filename,
    create_social_post_entries,
)

DUMMY_URL_TMPL = "https://medium.com/@test-user/{slug}-{rand}"


def _pick_first_unpublished() -> Optional[str]:
    """Return filename of the first article whose *posted_medium* == False."""
    excel_data, _ = download_excel_from_drive()
    articles_df = excel_data["articles"]

    mask = (articles_df["posted_medium"] == False)  # noqa: E712  (want bool comparison)
    if not mask.any():
        return None

    return str(articles_df[mask].iloc[0]["filename"])


def simulate_publish() -> None:
    filename = _pick_first_unpublished()
    if filename is None:
        print("✅ All articles already marked as published – nothing to do.")
        return

    # --- Build a fake Medium URL ------------------------------------------------
    slug_base = filename.replace("_", "-").replace(".md", "")
    dummy_url = DUMMY_URL_TMPL.format(slug=slug_base, rand=random.randint(1000, 9999))

    # --- Update the articles sheet ---------------------------------------------
    update_article_entry(
        filename=filename,
        updates={
            "posted_medium": True,
            "medium_url": dummy_url,
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    print(f"[INFO] Marked '{filename}' as posted on Medium → {dummy_url}")

    # --- Add social-post tasks --------------------------------------------------
    article_id = get_article_id_by_filename(filename)
    if article_id is None:
        print("[WARN] Could not resolve article_id – social posts not created.")
        return

    num_posts = create_social_post_entries(article_id, dummy_url)
    print(f"[INFO] Created {num_posts} pending social-post rows for article {article_id}.")

    print("🎉 Simulation complete.")


if __name__ == "__main__":
    simulate_publish() 
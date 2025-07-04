"""Centralised credential loader for LegittAgents.

This module reads the structured JSON found at
`Config/credentials.json` (or the path specified by the
`CREDENTIALS_FILE` environment variable) and

1. Exposes accessor helpers so the rest of the codebase can simply do::

       from core.credentials import google, user
       google_creds  = google()            # → dict
       twitter_creds = user()["twitter"]   # → dict for ACTIVE_USER

2.   *Back-compat patch* – it pre-populates ``os.environ`` with all the
     Google-Drive related values so the existing code that still relies on
     ``os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")`` etc. keeps working
     unchanged.  Environment variables that are already set are **NOT**
     overwritten – explicit user configuration always wins.

The helper assumes the following JSON structure (truncated):

```
{
  "google": {
    "service_account_json": "…",
    "drive_folder_id":      "…",
    "google_email":         "…",
    "google_password":      "…",
    "shared_drive_id":      "…",
    "drive_scope":          "…"
  },
  "users": {
    "user1": {
      "twitter":  { … },
      "linkedin": { … },
      "medium":   { … }
    },
    …
  }
}
```

If *ACTIVE_USER* isn't set, the first key in the "users" object is used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping

__all__ = [
    "google",
    "global_cfg",
    "users",
    "user",
    "save",  # so callers (token refreshers) can persist updates
]

# ---------------------------------------------------------------------------
# Locate and load the credentials JSON once at import time
# ---------------------------------------------------------------------------
_env_path = os.getenv("CREDENTIALS_FILE")
if _env_path and _env_path.strip():
    _DEFAULT_PATH = Path(_env_path)
else:
    _DEFAULT_PATH = Path(__file__).resolve().parent.parent / "Config" / "credentials.json"

if not _DEFAULT_PATH.exists():
    raise FileNotFoundError(f"Credentials file not found at {_DEFAULT_PATH}")

with _DEFAULT_PATH.open("r", encoding="utf-8") as _fp:
    _DATA: MutableMapping[str, Any] = json.load(_fp)  # mutable so updates stick

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def google() -> Mapping[str, Any]:
    """Return the top-level *google* credential section as a mapping."""
    return _DATA.get("google", {})


def users() -> Mapping[str, Any]:
    """Return the *users* mapping (user-id → creds dict)."""
    return _DATA.get("users", {})


def _default_user_id() -> str:
    return os.getenv("ACTIVE_USER") or next(iter(users().keys()))


def user(user_id: str | None = None) -> MutableMapping[str, Any]:
    """Return the credential mapping for *user_id* (defaults to ACTIVE_USER)."""
    uid = user_id or _default_user_id()
    u = users().get(uid)
    if u is None:
        raise KeyError(f"No such user id in credentials JSON: {uid!r}")
    return u  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Backwards-compat: pre-populate environment variables so existing code that
# still relies on os.getenv continues to work without modification.
# ---------------------------------------------------------------------------

# _GOOGLE_MAP = {
#     "service_account_json": "GOOGLE_SERVICE_ACCOUNT_JSON",
#     "drive_folder_id": "DRIVE_FOLDER_ID",
#     "google_email": "GOOGLE_EMAIL",
#     "google_password": "GOOGLE_PASSWORD",
#     "shared_drive_id": "SHARED_DRIVE_ID",
#     "drive_scope": "DRIVE_SCOPE",
# }

# for _json_key, _env_key in _GOOGLE_MAP.items():
#     _val = google().get(_json_key, "")
#     if _val and not os.getenv(_env_key):
#         os.environ[_env_key] = str(_val)

# # ---------------------------------------------------------------------------
# Global (app-wide) configuration helpers
# ---------------------------------------------------------------------------

def global_cfg() -> Mapping[str, Any]:
    """Return the top-level *global* configuration mapping (may be empty)."""
    return _DATA.get("global", {})

# Env vars sourced from the new top-level "global" section
_GLOBAL_MAP = {
    "keywords_file": "KEYWORDS_FILE",
    "seed_file": "SEED_FILE",
    "blog_content_database": "BLOG_CONTENT_DATABASE",
    "excel_name": "EXCEL_NAME",
    "demo_link": "DEMO_LINK",
}

for _json_key, _env_key in _GLOBAL_MAP.items():
    _val = global_cfg().get(_json_key, "")
    if _val and not os.getenv(_env_key):
        os.environ[_env_key] = str(_val)

# ---------------------------------------------------------------------------
# Persistence helper so token-refresh scripts can write back into the same file
# without re-implementing JSON handling everywhere.
# ---------------------------------------------------------------------------

def save() -> None:
    """Flush the in-memory credential data back to disk (pretty-printed)."""
    with _DEFAULT_PATH.open("w", encoding="utf-8") as _fp:
        json.dump(_DATA, _fp, indent=2) 


if __name__ == "__main__":
    # print(users())
    # print(_default_user_id())
    print('medium', user()['medium'], "\n")
    print('linkedin', user()['linkedin'], "\n")
    print('twitter', user()['twitter'], "\n")
    print('google', google(), "\n")
    # print('global_cfg', global_cfg())   

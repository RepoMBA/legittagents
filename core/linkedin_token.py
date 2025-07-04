import os
import secrets
import threading
import webbrowser
import requests
import urllib.parse

from urllib.parse import urlencode
from flask import Flask, redirect, request
# Centralised credential handling
from core.credentials import user as _user_creds, save as _save_creds

# Load .env after credentials so user overrides still win
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ──────────────────────────────────────────────────────────────
linkedin_credentials = _user_creds().get("linkedin", {})
CLIENT_ID     = linkedin_credentials["client_id"]
CLIENT_SECRET = linkedin_credentials["client_secret"]   # if you're truly using PKCE you can leave this blank
REDIRECT_URL  = linkedin_credentials["redirect_url"]


LINKEDIN_LOCAL_SERVER = linkedin_credentials.get("local_server", "http://localhost:8001/")

# Determine scopes – fall back to sensible defaults if missing/empty in creds
DEFAULT_SCOPES = [
    "profile",       # basic profile
    "email",         # email (optional but common)
    "w_member_social", # post to feed
    "openid"         # openid
]

# creds["scope"] may be a list or a single space-separated string
_sc = linkedin_credentials.get("scope", "") if isinstance(linkedin_credentials, dict) else ""
if isinstance(_sc, list):
    SCOPE_LIST: list[str] = _sc
elif isinstance(_sc, str) and _sc.strip():
    SCOPE_LIST = _sc.split()
else:
    SCOPE_LIST = DEFAULT_SCOPES

SCOPE = SCOPE_LIST
STATE         = secrets.token_urlsafe(16)
# ─── PORT DERIVED FROM REDIRECT_URI ──────────────────────────────────────
# Automatically pick the port specified in the REDIRECT_URI so the Flask
# server always listens on the correct one even after env-file edits.
_parsed = urllib.parse.urlparse(REDIRECT_URL)

# --- Always use fixed local port for LinkedIn OAuth ---
PORT = 8001

# ─────────────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/auth/linkedin")
def auth():
    params = {
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URL,
        "scope":         " ".join(SCOPE),
        "state":         STATE
    }
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(params)
    return redirect(auth_url)


@app.route("/auth/linkedin/callback")
def callback():
    # 1) error from LinkedIn?
    if "error" in request.args:
        desc = request.args.get("error_description", "Unknown error")
        return f"❌ LinkedIn error: {desc}", 400

    # 2) CSRF check
    if request.args.get("state") != STATE:
        return "❌ Invalid state parameter", 400

    # 3) exchange code for token
    code = request.args["code"]
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URL,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    resp.raise_for_status()
    token_data = resp.json()
    
    access_token = token_data["access_token"]

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }

    resp = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers)
    resp.raise_for_status()
    profile = resp.json()
    member_id = profile["sub"]
    author_urn = f"urn:li:person:{member_id}"
    token_data["author_urn"] = author_urn
    

    # 4) persist to credentials JSON under current user
    linkedin_credentials.update({
        "access_token": access_token,
        "scope": token_data.get("scope", ""),
        "author_urn": author_urn,
        "expires_in": token_data.get("expires_in", 0),
        "token_type": token_data.get("token_type", ""),
        "id_token": token_data.get("id_token", ""),
    })
    _save_creds()

    # 5) shut down the dev server
    shutdown = request.environ.get("werkzeug.server.shutdown")
    if shutdown:
        shutdown()


    return (
        f"Access token: {access_token}<br>"
        f"Granted scopes: {token_data.get('scope')}<br>"
        f"Author urn: {author_urn}"
    )


def refresh_linkedin_token():
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True,
    ).start()
    webbrowser.open("http://localhost:8001/auth/linkedin")


def main():
    # Run Flask in the main thread (blocking) so the process stays alive when
    # this script is executed directly from the command line.
    webbrowser.open("http://localhost:8001/auth/linkedin")
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
    # or run it in a thread and join a short moment


if __name__ == "__main__":
    main()

import os
import json
import secrets
import threading
import webbrowser
import requests

from urllib.parse import urlencode
from flask import Flask, redirect, request
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ──────────────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("LINKEDIN_REDIRECT_URI")
STATE         = secrets.token_urlsafe(16)
TOKEN_FILE    = os.getenv("LINKEDIN_TOKEN_FILE")
with open(TOKEN_FILE) as f:
    creds = json.load(f)
SCOPE = creds["scope"]
# ──────────────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/auth/linkedin")
def auth():
    params = {
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
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
            "redirect_uri":  REDIRECT_URI,
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
    

    # 4) save to disk
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)


    # 5) shut down the dev server
    shutdown = request.environ.get("werkzeug.server.shutdown")
    if shutdown:
        shutdown()


    return (
        f"Access token: {access_token}<br>"
        f"Granted scopes: {token_data.get('scope')}<br>"
        f"Author urn: {author_urn}"
    )




def main():
    # launch the Flask app
    threading.Thread(target=lambda: app.run(port=8000, debug=False)).start()

    # open the browser to start the flow
    webbrowser.open("http://localhost:8000/auth/linkedin")



if __name__ == "__main__":
    main()

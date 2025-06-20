#!/usr/bin/env python3
import requests
import urllib.parse
import secrets
import hashlib, base64
import json
import os
from flask import Flask, request, redirect
import webbrowser

from dotenv import load_dotenv

load_dotenv()

def make_code_challenge(verifier: str) -> str:
    # SHA256 hash the verifier
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    # Base64-url-encode it and strip any '=' padding
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

# ─── CONFIG ──────────────────────────────────────────────────────────────
TOKEN_FILE    = os.getenv("TWITTER_TOKEN_FILE")
LOCAL_SERVER = os.getenv("LOCAL_SERVER")
STATE         = secrets.token_urlsafe(16)
if not os.path.exists(TOKEN_FILE):
    raise FileNotFoundError(f"No such file: {TOKEN_FILE}")

with open(TOKEN_FILE) as f:
    creds = json.load(f)

CLIENT_ID     = creds["client_id"]
CLIENT_SECRET = creds["client_secret"]   # if you’re truly using PKCE you can leave this blank
REDIRECT_URI  = creds["redirect_url"]
CODE_VERIFIER = creds["verifier"]
CODE_CHALLENGE= make_code_challenge(CODE_VERIFIER)
SCOPE = creds["scope"]

# ──────────────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route('/')
def index():
    # Redirect user to X.com for authorization
    params = {
        'response_type':       'code',
        'client_id':           CLIENT_ID,
        'redirect_uri':        REDIRECT_URI,
        'scope':               SCOPE,
        'state':               STATE,
        'code_challenge':      CODE_CHALLENGE,
        'code_challenge_method':'S256',
    }
    params_str = "&".join(
        f"{k}={urllib.parse.quote(v, safe='')}"
        for k, v in params.items()
    )
    auth_url = f"https://x.com/i/oauth2/authorize?{params_str}"
    return redirect(auth_url)

@app.route('/auth/twitter/callback')
def callback():
    error = request.args.get('error')
    if error:
        return f"Error: {error}", 400
    code = request.args.get('code')
    returned_state = request.args.get('state')
    if returned_state != STATE:
        return 'Invalid state', 400

    # Exchange authorization code for user-context bearer token
    token_url = "https://api.x.com/2/oauth2/token"
    data = {
        'grant_type':    'authorization_code',
        'code':          code,
        'redirect_uri':  REDIRECT_URI,
        'code_verifier': CODE_VERIFIER,
        'client_id':     CLIENT_ID,
    }
    resp = requests.post(
        token_url,
        data=data,
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if not resp.ok:
        print("Status:", resp.status_code)
        print("Body:", resp.text)

    token_json = resp.json()
    # Save token to file
    creds.update({
        "access_token": token_json["access_token"],
        "scope": token_json["scope"],
    })

    with open(TOKEN_FILE, "w") as f:
        json.dump(creds, f, indent=2)

    return '✅ Authentication successful! Token saved.', 200

def main():
    # print(f"▶️  Open http://localhost:8000 in your browser to start authentication flow.")
    webbrowser.open(LOCAL_SERVER)
    os.makedirs(os.path.dirname(TOKEN_FILE) or '.', exist_ok=True)
    app.run(host='0.0.0.0', port=8000, debug=True)

if __name__ == '__main__':
    main()

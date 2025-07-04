#!/usr/bin/env python3
import requests
import urllib.parse
import secrets
import hashlib, base64
from flask import Flask, request, redirect
import webbrowser
import threading

# Centralised credential access
from core.credentials import user as _user_creds, save as _save_creds

# Keep dotenv for supplementary vars (e.g. OPENAI_API_KEY) but load AFTER we
# patched env vars via the credentials module import above.
from dotenv import load_dotenv

load_dotenv()

def make_code_challenge(verifier: str) -> str:
    # SHA256 hash the verifier
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    # Base64-url-encode it and strip any '=' padding
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

# ─── CONFIG ──────────────────────────────────────────────────────────────
PORT = 8000
STATE = secrets.token_urlsafe(16)

# Resolve credentials for the active user (defaults to the first user key)
twitter_credentials = _user_creds().get("twitter", {})

CLIENT_ID     = twitter_credentials["client_id"]
CLIENT_SECRET = twitter_credentials["client_secret"]   # if you're truly using PKCE you can leave this blank
REDIRECT_URL  = twitter_credentials["redirect_url"]
CODE_VERIFIER = twitter_credentials["verifier"]
SCOPE = twitter_credentials["scope"]
CODE_CHALLENGE = make_code_challenge(CODE_VERIFIER)
TWITTER_LOCAL_SERVER = twitter_credentials.get("local_server", "http://localhost:8000/")


# ──────────────────────────────────────────────────────────────────────────

flaskApp = Flask(__name__)


@flaskApp.route('/')
def index():
    # Redirect user to X.com for authorization
    params = {
        'response_type':       'code',
        'client_id':           CLIENT_ID,
        'redirect_uri':        REDIRECT_URL,
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

@flaskApp.route('/auth/twitter/callback')
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
        'redirect_uri':  REDIRECT_URL,
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

    # Guard against missing access token to prevent KeyError
    if "access_token" not in token_json:
        # Return detailed error information to aid debugging
        return (
            f"Failed to retrieve access token. Response from Twitter: {token_json}",
            400,
        )

    # Persist the refreshed token back into the shared credentials JSON
    twitter_credentials["access_token"] = token_json["access_token"]
    twitter_credentials["scope"] = token_json.get("scope", "")
    _save_creds()

    # Gracefully stop the local dev server so Streamlit can continue
    shutdown = request.environ.get("werkzeug.server.shutdown")
    if shutdown:
        shutdown()

    return "✅ Authentication successful! Token saved. You may close this tab.", 200

def refresh_twitter_token():
    # Launch Flask in a background thread so Streamlit doesn't block
    threading.Thread(
        target=lambda: flaskApp.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True,
    ).start()

    # Open browser to kick-off OAuth flow (root "/" route redirects to X.com)
    webbrowser.open(str(TWITTER_LOCAL_SERVER))
    # flaskApp.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)

def main():
    webbrowser.open(str(TWITTER_LOCAL_SERVER))
    flaskApp.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)

if __name__ == '__main__':
    main()

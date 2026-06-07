"""
One-time script to obtain a Google OAuth2 refresh token for Calendar access.

Steps:
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create an OAuth 2.0 Client ID (Desktop app type)
  3. Download the JSON and note client_id and client_secret
  4. Run: uv run scripts/get_refresh_token.py
  5. Paste the printed values into your .env
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",  # downloaded from Google Cloud Console
    scopes=SCOPES,
)
creds = flow.run_local_server(port=0)

print("\n── Add these to your .env ──────────────────────")
print(f"GOOGLE_CLIENT_ID={creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
print("────────────────────────────────────────────────\n")

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(_DIR, "token.json")
CREDS_FILE = os.path.join(_DIR, "credentials.json")

def get_calendar_creds():
    """Return valid Google Calendar credentials, refreshing or re-authing as needed."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds

if __name__ == "__main__":
    get_calendar_creds()
    print("Authentication successful. token.json saved.")

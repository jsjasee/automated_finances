# reauth_gmail.py  (run on your laptop)
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

flow = InstalledAppFlow.from_client_secrets_file("secrets/Desktop app.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
open("secrets/gmail_token.json", "w").write(creds.to_json())
print("Wrote gmail_token.json")

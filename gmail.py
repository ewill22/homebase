import imaplib
from dotenv import load_dotenv
import os

load_dotenv()

EMAIL = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

def get_imap():
    """Return an authenticated IMAP connection to Gmail."""
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(EMAIL, PASSWORD)
    return conn

def delete_emails(search_criteria):
    """
    Search for emails matching criteria and move them to Trash.
    search_criteria: an IMAP search string, e.g. '(UNSEEN FROM "google")'
    Returns the count of deleted emails.
    """
    conn = get_imap()
    conn.select("INBOX")

    # Search returns a list of email IDs matching the criteria
    _, data = conn.search(None, search_criteria)
    email_ids = data[0].split()

    for eid in email_ids:
        # Gmail uses a special label to trash — move then expunge
        conn.store(eid, "+X-GM-LABELS", "\\Trash")
        conn.store(eid, "+FLAGS", "\\Deleted")

    conn.expunge()
    conn.logout()
    return len(email_ids)

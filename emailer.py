import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
import os

load_dotenv()

FROM = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

def send_email(subject, body, to=None, attachments=None):
    """
    Send an email with optional file attachments.
    attachments: list of file paths to attach, e.g. ['work/leads_simple.sql']
    """
    to = to or FROM

    msg = MIMEMultipart("alternative" if isinstance(body, dict) else "mixed")
    msg["Subject"] = subject
    msg["From"] = FROM
    msg["To"] = to

    if isinstance(body, dict):
        # body = {"text": "...", "html": "..."}
        msg.attach(MIMEText(body.get("text", ""), "plain", "utf-8"))
        msg.attach(MIMEText(body.get("html", ""), "html", "utf-8"))
    else:
        msg.attach(MIMEText(body, "plain", "utf-8"))

    for filepath in (attachments or []):
        with open(filepath, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(filepath)}")
        msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(FROM, PASSWORD)
        server.sendmail(FROM, to, msg.as_string())

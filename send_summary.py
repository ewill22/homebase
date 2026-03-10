import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

LOG = r"C:\Users\eewil\homebase\send_summary.log"

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

try:
    from commands import cmd_home_summary
    from emailer import send_email

    now = datetime.now(ZoneInfo("America/New_York"))
    subject = "homebase | " + now.strftime("%a %b %d, %I:%M %p")
    send_email(subject, cmd_home_summary(), to="ewill22@gmail.com")
    log("OK - summary sent")

except Exception as e:
    log(f"ERROR - {e}\n{traceback.format_exc()}")
    raise

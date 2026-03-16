import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

LOG = r"C:\Users\eewil\homebase\send_summary.log"

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

try:
    from config import get_config
    from commands import cmd_home_summary
    from emailer import send_email
    from logger import log_event

    cfg = get_config()
    tz  = ZoneInfo(cfg["user"]["timezone"])
    now = datetime.now(tz)

    subject = "homebase | " + now.strftime("%a %b %d, %I:%M %p")
    send_email(subject, cmd_home_summary(), to=cfg["user"]["send_to_email"])
    log("OK - summary sent")
    log_event("summary_sent", message="OK", detail=subject)

except Exception as e:
    log(f"ERROR - {e}\n{traceback.format_exc()}")
    try:
        from logger import log_event
        log_event("error", status="error", message=str(e), detail=traceback.format_exc())
    except Exception:
        pass
    raise

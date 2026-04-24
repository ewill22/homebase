"""
strain_sync_run.py — Guapa Strains daily sync entry point.
Runs sync_crops_catalog() across all dispensaries and logs to guapa.strain_stock.
Scheduled via Windows Task Scheduler: "Guapa Strains Sync"

Stdout/stderr are captured by the bat wrapper's `>> logs/strain_sync.log 2>&1`.
Do NOT open that file from Python — Windows won't allow a second handle.
"""
import sys
import traceback
from datetime import datetime


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
          flush=True)


try:
    from strain_sync import sync_crops_catalog
    results = sync_crops_catalog()
    log(f"OK - sync_crops_catalog: {len(results)} products logged")
except Exception as e:
    log(f"ERROR - {e}\n{traceback.format_exc()}")
    sys.exit(1)

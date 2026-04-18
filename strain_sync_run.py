"""
strain_sync_run.py — Guapa Strains daily sync entry point.
Runs sync_crops_catalog() across all dispensaries and logs to guapa.strain_stock.
Scheduled via Windows Task Scheduler: "Guapa Strains Sync"
"""
import traceback
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).parent / "logs" / "strain_sync.log"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


try:
    from strain_sync import sync_crops_catalog
    results = sync_crops_catalog()
    log(f"OK - sync_crops_catalog: {len(results)} products logged")
except Exception as e:
    log(f"ERROR - {e}\n{traceback.format_exc()}")
    raise

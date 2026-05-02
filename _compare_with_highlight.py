"""
Manual trigger for the Secret Meetings side-by-side comparison HTML.
Pulls the latest Conservatory snapshot from dispensary_menu and regenerates
the HTML at logs/ + iCloud Drive. Run this when you want to refresh the
artifact without sending a "going to" email.

Usage:
    python _compare_with_highlight.py            # uses latest Conservatory snapshot
    python _compare_with_highlight.py med-leaf   # latest Med Leaf snapshot
"""
import decimal
import sys

import dispensary_planner as dp
from db import get_connection


def latest_snapshot(dispensary_display_name):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""SELECT * FROM dispensary_menu
                   WHERE dispensary=%s
                     AND snapshot_id=(SELECT snapshot_id FROM dispensary_menu
                                      WHERE dispensary=%s
                                      ORDER BY captured_at DESC LIMIT 1)""",
                (dispensary_display_name, dispensary_display_name))
    rows = cur.fetchall()
    cur.close(); conn.close()
    for p in rows:
        for k, v in list(p.items()):
            if isinstance(v, decimal.Decimal):
                p[k] = float(v)
    return rows


if __name__ == "__main__":
    alias = sys.argv[1] if len(sys.argv) > 1 else "conservatory"
    store = dp._store_for_alias(alias)
    if not store:
        print(f"unknown alias: {alias}")
        sys.exit(1)
    name = store[0]
    products = latest_snapshot(name)
    if not products:
        print(f"no snapshot found for {name} - email 'going to {alias}' first")
        sys.exit(1)
    paths = dp.write_comparison_html(products, name)
    print(f"refreshed from {len(products)} SKUs:")
    for k, v in paths.items():
        print(f"  {k}: {v}")

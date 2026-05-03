"""
Manual trigger for the Secret Meetings side-by-side comparison HTML.
Regenerates the artifact (Conservatory + Med Leaf, both stacked) from
the latest snapshots in dispensary_menu. Use when you want to refresh
without sending a "going to" email.

Usage:
    python _compare_with_highlight.py
"""
import dispensary_planner as dp


if __name__ == "__main__":
    paths = dp.write_comparison_html()
    print("refreshed:")
    for k, v in paths.items():
        print(f"  {k}: {v}")

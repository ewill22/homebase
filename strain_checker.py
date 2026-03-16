"""
strain_checker.py (homebase) — thin reader over guapa.strain_stock.
Data collection and sync live in guapa-data/strains/strain_checker.py.
This module just fetches the latest snapshot for display in the morning email.
"""

DEFAULT_STRAIN = "secret meetings"


def get_strain_stock(strain=DEFAULT_STRAIN):
    """
    Return the latest in-stock results for a strain from guapa.strain_stock.
    Each result: {dispensary, name, brand, category, price, url, new_batch,
                  listed_at, package_id, strain_type, crops_grower}
    """
    from db import get_connection
    conn = get_connection()
    cur  = conn.cursor(dictionary=True)

    # Get the most recent checked_at for this strain
    cur.execute(
        "SELECT MAX(checked_at) FROM guapa.strain_stock WHERE strain_name = %s AND in_stock = 1",
        (strain,)
    )
    row = cur.fetchone()
    latest = list(row.values())[0] if row else None

    if not latest:
        cur.close()
        conn.close()
        return []

    cur.execute("""
        SELECT dispensary, strain_name, brand, product_name AS name, category,
               price, menu_url AS url, listed_at, package_id,
               strain_type, crops_grower, new_batch
        FROM guapa.strain_stock
        WHERE strain_name = %s AND in_stock = 1 AND checked_at = %s
        ORDER BY dispensary
    """, (strain, latest))
    results = cur.fetchall()
    cur.close()
    conn.close()

    # Convert Decimal price to string for email rendering
    for r in results:
        if r.get("price") is not None:
            r["price"] = f"${float(r['price']):.0f}"
    return results

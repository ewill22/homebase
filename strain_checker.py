"""
strain_checker.py (homebase) — thin reader over guapa.strain_stock.
Data collection and sync live in guapa-data/strains/strain_checker.py.
This module just fetches the latest snapshot for display in the morning email.
"""

# Named strains always tracked regardless of terpene profile
TRACKED_STRAINS = ["secret meetings", "high society"]

# Terpene trio that defines the vibe — any Crops strain in stock with all three
# will show up dynamically (beta_caryophyllene dominant + limonene + myrcene)
TERPENE_TRIO = ("beta_caryophyllene", "limonene", "beta_myrcene")


def _price_str(r):
    if r.get("price") is not None:
        r["price"] = f"${float(r['price']):.0f}"
    return r


def get_strain_stock(strain):
    """
    Return the latest in-stock results for a single strain name.
    Each result: {dispensary, strain_name, name, brand, category, price, url,
                  new_batch, listed_at, package_id, strain_type, crops_grower}
    """
    from db import get_connection
    conn = get_connection()
    cur  = conn.cursor(dictionary=True)

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

    return [_price_str(r) for r in results]


def get_terpene_matched_stocks(exclude=None):
    """
    Find any in-stock Crops strains (not in exclude list) where all three
    terpenes in TERPENE_TRIO are present — dynamically surfaces new similar strains.
    """
    from db import get_connection
    exclude_lower = [s.lower() for s in (exclude or [])]

    conn = get_connection()
    cur  = conn.cursor(dictionary=True)

    # Get latest checked_at per matching strain
    cur.execute("""
        SELECT strain_name, MAX(checked_at) AS latest
        FROM guapa.strain_stock
        WHERE crops_grower = 1 AND in_stock = 1
          AND beta_caryophyllene > 0 AND limonene > 0 AND beta_myrcene > 0
        GROUP BY strain_name
    """)
    candidates = {r["strain_name"]: r["latest"] for r in cur.fetchall()
                  if r["strain_name"].lower() not in exclude_lower}

    results = []
    for strain_name, latest in candidates.items():
        cur.execute("""
            SELECT dispensary, strain_name, brand, product_name AS name, category,
                   price, menu_url AS url, listed_at, package_id,
                   strain_type, crops_grower, new_batch
            FROM guapa.strain_stock
            WHERE strain_name = %s AND in_stock = 1 AND checked_at = %s
            ORDER BY dispensary
        """, (strain_name, latest))
        results.extend([_price_str(r) for r in cur.fetchall()])

    cur.close()
    conn.close()
    return results


def get_all_strain_hits():
    """
    Fetch all tracked strains + any terpene-matched Crops strains in stock.
    Returns (hits, tracked_found) where tracked_found is list of tracked strain
    names that have stock today.
    """
    hits = []
    tracked_found = []
    for strain in TRACKED_STRAINS:
        rows = get_strain_stock(strain)
        if rows:
            tracked_found.append(strain)
        hits.extend(rows)

    # Terpene matches not already in tracked list
    hits.extend(get_terpene_matched_stocks(exclude=TRACKED_STRAINS))
    return hits, tracked_found

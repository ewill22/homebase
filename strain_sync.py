#!/usr/bin/env python3
"""
NJ Dispensary Strain Stock Checker
Watches multiple dispensaries simultaneously:
  • Med Leaf        (DispenseApp API)
  • City Leaves     (DispenseApp API)
  • Conservatory    (DispenseApp API)
  • Green Wellness  (DispenseApp API)
  • Brute's Roots   (Dutchie API)
  • The Botanist    (Dutchie API)
  • Public Absecon  (Dutchie API)
  • AC LEEF         (Dutchie API)
  • MPX NJ          (Dutchie API)
  • Juniper Lane    (Dutchie API)
  • Atlantic Flower (Dutchie API)
  • Cannabist ML    (Sweed/HTML)

Usage:
    python strain_checker.py                       # checks every 5 min
    python strain_checker.py --interval 60         # check every 60 seconds
    python strain_checker.py --strain "Blue Dream" # different strain
    python strain_checker.py --once                # single check and exit
    python strain_checker.py --list                # list all products everywhere
"""

import argparse
import json
import ssl
import subprocess
import sys
import time
import uuid
import urllib.parse
import urllib.request
from datetime import datetime
from curl_cffi import requests as cffi_requests

DEFAULT_STRAIN   = "crops secret meetings"
DEFAULT_INTERVAL = 300  # seconds

# Known Crops Cannabis strains — used to detect white-label listings
# (same strain sold under a different brand name at some dispensaries)
CROPS_STRAINS = [
    "secret meetings",
    "watermelon mint",
    "high society",
    "soap",
    "mac stomper",
    "super lemon g",
    "animal mint cake",
    "ruby violet",
    "donny burger",
    "road trip",
    "candy pav",   # handles "Candy Pavé" and encoding variants
    "jon woo",
]

_EXCLUDED_CATEGORIES = {"vaporizer", "vaporizers", "vape", "vapes", "cartridge",
                        "cartridges", "disposable", "disposables", "concentrate",
                        "concentrates"}

def _is_vape_category(cat_name):
    return any(w in cat_name.lower() for w in ("vape", "vaporizer", "cartridge", "disposable", "dank tank", "aio"))

def _is_vape_product(name):
    nl = name.lower()
    return any(w in nl for w in ("vape", "cartridge", "disposable", "dank tank", "aio", "pod"))

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


# ══════════════════════════════════════════════════════════════════════════════
# DispenseApp — generic (used by Med Leaf, City Leaves, Conservatory)
# ══════════════════════════════════════════════════════════════════════════════

_DA_BASE    = "https://api.dispenseapp.com"
_DA_API_KEY = "49dac8e0-7743-11e9-8e3f-a5601eb2e936"

# (display_name, venue_id, org_id, menu_url)
DISPENSEAPP_STORES = [
    ("Med Leaf",     "9e34aad030c6f68f", "49daba764d6e90e5",
     "https://menus.dispenseapp.com/9e34aad030c6f68f/menu"),
    ("City Leaves",  "94b97cba76dcbc82", "06f4c19c09247cd3",
     "https://menus.dispenseapp.com/94b97cba76dcbc82/menu"),
    ("Conservatory", "482264628c7deb3e", "c78b003ea247551e",
     "https://menus.dispenseapp.com/482264628c7deb3e/menu"),
    ("Green Wellness", "54d4d91292086381", "99388c073647bf1c",
     "https://menus.dispenseapp.com/54d4d91292086381/menu"),
]


def _da_get(url, token, menu_url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://menus.dispenseapp.com/",
        "api-key": _DA_API_KEY,
        "x-prospect-token": token,
        "x-url": menu_url,
    })
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as r:
        return json.loads(r.read())


def _da_guest_token(org_id, menu_url):
    token = str(uuid.uuid4())
    _da_get(f"{_DA_BASE}/user/me?organizationId={org_id}", token, menu_url)
    return token


def dispenseapp_search(name, venue_id, org_id, menu_url, strain):
    token = _da_guest_token(org_id, menu_url)
    cats_resp = _da_get(
        f"{_DA_BASE}/v1/venues/{venue_id}/product-categories?orderPickUpType=IN_STORE",
        token, menu_url,
    )
    categories = cats_resp if isinstance(cats_resp, list) else cats_resp.get("data", [])
    strain_lower = strain.lower()
    # Split into words so "crops secret meetings" matches "CROPS | SECRET MEETINGS"
    strain_words = strain_lower.split()
    matches = []
    for cat in categories:
        cat_id   = cat.get("id") or cat.get("_id")
        cat_name = cat.get("name") or cat.get("productCategoryName", "?")
        if _is_vape_category(cat_name):
            continue
        try:
            url = (f"{_DA_BASE}/v1/venues/{venue_id}/product-categories/{cat_id}"
                   f"/products?skip=0&limit=100&orderPickUpType=IN_STORE")
            resp = _da_get(url, token, menu_url)
            products = resp if isinstance(resp, list) else resp.get("data", [])
            for p in products:
                pname = p.get("name", "")
                haystack = (pname + " " + p.get("strain", "")).lower()
                if all(w in haystack for w in strain_words):
                    price = p.get("price")
                    labs   = p.get("labs") or {}
                    images = p.get("images") or []
                    image_url  = images[0].get("fileUrl") if images else None
                    created_ms = p.get("created")
                    try:
                        from datetime import datetime as _dt
                        listed_at = _dt.fromisoformat(str(created_ms).replace("Z", "+00:00")).replace(tzinfo=None) if created_ms else None
                    except Exception:
                        listed_at = None
                    matches.append({
                        "dispensary":   name,
                        "name":         pname,
                        "brand":        (p.get("brand") or {}).get("name"),
                        "category":     cat_name,
                        "price":        f"${price}" if price else None,
                        "url":          menu_url,
                        "listed_at":    listed_at,
                        "package_id":   p.get("posProductId"),
                        "strain_type":  p.get("cannabisType"),
                        "potency":      labs.get("potency"),
                        "thc":          labs.get("thc"),
                        "thca":         labs.get("thcA"),
                        "cbd":          labs.get("cbd"),
                        "cbda":         labs.get("cbdA"),
                        "cbg":          labs.get("cbg"),
                        "cbn":          labs.get("cbn"),
                        "limonene":     labs.get("limonene"),
                        "beta_myrcene": labs.get("betaMyrcene"),
                        "beta_caryophyllene": labs.get("betaCaryophyllene"),
                        "humulene":     labs.get("humulene"),
                        "alpha_pinene": labs.get("alphaPinene"),
                        "beta_pinene":  labs.get("betaPinene"),
                        "linalool":     labs.get("linalool"),
                        "ocimene":      labs.get("ocimene"),
                        "terpinolene":  labs.get("terpinolene"),
                        "bisabolol":    labs.get("bisabolol"),
                        "product_image": image_url,
                    })
        except Exception:
            pass
    return matches


def dispenseapp_list_all(name, venue_id, org_id, menu_url):
    token = _da_guest_token(org_id, menu_url)
    cats_resp = _da_get(
        f"{_DA_BASE}/v1/venues/{venue_id}/product-categories?orderPickUpType=IN_STORE",
        token, menu_url,
    )
    categories = cats_resp if isinstance(cats_resp, list) else cats_resp.get("data", [])
    print(f"\n  {'─'*50}")
    print(f"  {name}  •  {menu_url}")
    print(f"  {'─'*50}")
    for cat in categories:
        cat_id   = cat.get("id") or cat.get("_id")
        cat_name = cat.get("name") or cat.get("productCategoryName", "?")
        try:
            url = (f"{_DA_BASE}/v1/venues/{venue_id}/product-categories/{cat_id}"
                   f"/products?skip=0&limit=100&orderPickUpType=IN_STORE")
            resp = _da_get(url, token, menu_url)
            products = resp if isinstance(resp, list) else resp.get("data", [])
            seen = set()
            rows = []
            for p in products:
                pname = p.get("name", "").strip()
                if pname and pname not in seen:
                    seen.add(pname)
                    price = p.get("price")
                    rows.append(f"    • {pname}" + (f"  —  ${price}" if price else ""))
            if rows:
                print(f"\n  [{cat_name}]")
                for r in rows:
                    print(r)
        except Exception:
            pass


def dispenseapp_full_flower_menu(name, venue_id, org_id, menu_url):
    """Pull every flower SKU at a DispenseApp store (no strain filter).
    Captures regular price, discounted price, and the full lab panel.
    Used by dispensary_planner — not by the daily Crops sweep."""
    token = _da_guest_token(org_id, menu_url)
    cats_resp = _da_get(
        f"{_DA_BASE}/v1/venues/{venue_id}/product-categories?orderPickUpType=IN_STORE",
        token, menu_url,
    )
    categories = cats_resp if isinstance(cats_resp, list) else cats_resp.get("data", [])
    out = []
    for cat in categories:
        cat_name = cat.get("name") or cat.get("productCategoryName", "")
        if "flower" not in cat_name.lower() and "pre-roll" not in cat_name.lower() and "preroll" not in cat_name.lower():
            continue
        cat_id = cat.get("id") or cat.get("_id")
        try:
            url = (f"{_DA_BASE}/v1/venues/{venue_id}/product-categories/{cat_id}"
                   f"/products?skip=0&limit=200&orderPickUpType=IN_STORE")
            resp = _da_get(url, token, menu_url)
            products = resp if isinstance(resp, list) else resp.get("data", [])
        except Exception:
            continue
        for p in products:
            pname = (p.get("name") or "").strip()
            if not pname:
                continue
            labs   = p.get("labs") or {}
            price  = p.get("price")
            disc_price = p.get("priceWithDiscounts")
            disc_pct   = p.get("discountValueFinal")
            sale_price = None
            if disc_price is not None and price is not None and disc_price < price:
                sale_price = disc_price
            offers = p.get("discounts") or []
            offer_label = None
            for o in offers:
                if o.get("productOfferType") == "SALE":
                    offer_label = "SALE"; break
            out.append({
                "dispensary":   name,
                "product_name": pname,
                "brand":        (p.get("brand") or {}).get("name"),
                "category":     cat_name,
                "strain_name":  (p.get("strain") or "").strip().lower() or None,
                "strain_type":  p.get("cannabisType"),
                "price":        price,
                "sale_price":   sale_price,
                "discount_pct": disc_pct if disc_pct else None,
                "discount_label": offer_label,
                "in_stock":     1 if p.get("isAvailable", True) else 0,
                "package_id":   p.get("posProductId"),
                "menu_url":     menu_url,
                "thc":          labs.get("thc"),
                "thca":         labs.get("thcA"),
                "cbd":          labs.get("cbd"),
                "cbda":         labs.get("cbdA"),
                "cbg":          labs.get("cbg"),
                "cbn":          labs.get("cbn"),
                "limonene":     labs.get("limonene"),
                "beta_myrcene": labs.get("betaMyrcene"),
                "beta_caryophyllene": labs.get("betaCaryophyllene"),
                "humulene":     labs.get("humulene"),
                "alpha_pinene": labs.get("alphaPinene"),
                "beta_pinene":  labs.get("betaPinene"),
                "linalool":     labs.get("linalool"),
                "ocimene":      labs.get("ocimene"),
                "terpinolene":  labs.get("terpinolene"),
                "bisabolol":    labs.get("bisabolol"),
            })
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Dutchie — generic (used by Brute's Roots, The Botanist, Public Absecon)
# ══════════════════════════════════════════════════════════════════════════════

_DU_GRAPHQL    = "https://dutchie.com/api-0/graphql"
_DU_QUERY_HASH = "c3dda0418c4b423ed26a38d011b50a2b8c9a1f8bde74b45f93420d60d2c50ae1"

_DU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "apollographql-client-name": "Marketplace (production)",
    "apollo-require-preflight": "true",
    "x-apollo-operation-name": "FilteredProducts",
    "Referer": "https://dutchie.com/",
    "Origin": "https://dutchie.com",
}

# (display_name, dispensary_id, menu_url)
DUTCHIE_STORES = [
    ("Brute's Roots",  "64b6b8cbb2618700094ec9b0",
     "https://dutchie.com/dispensary/brutes-roots-rec"),
    ("The Botanist",   "679aad3cb0ad9274a463dd63",
     "https://dutchie.com/dispensary/egg-harbor-rec-menu"),
    ("Public Absecon", "68375947efe8e3d70817c2a1",
     "https://dutchie.com/dispensary/public-absecon"),
    ("AC LEEF",        "66ec44db2f8b30dc518af663",
     "https://dutchie.com/dispensary/ac-leef"),
    ("MPX NJ",         "6430999beb61f100cb621870",
     "https://dutchie.com/dispensary/mpx-new-jersey-atlantic-city"),
    ("Juniper Lane",   "65157c45a898a30009c1cf97",
     "https://dutchie.com/dispensary/juniper-lane-atlantic-city"),
    ("Atlantic Flower", "6723b20c03fe2bab127498ca",
     "https://atlanticflowerdispensary.com/menu/"),
]


def _du_fetch_page(dispensary_id, page_num, per_page=100):
    variables = {
        "includeEnterpriseSpecials": False,
        "productsFilter": {
            "dispensaryId": dispensary_id,
            "pricingType": "rec",
            "strainTypes": [], "subcategories": [], "Status": "Active", "types": [],
            "useCache": True, "isDefaultSort": True, "sortBy": "brand", "sortDirection": 1,
            "bypassOnlineThresholds": False, "isKioskMenu": False,
            "removeProductsBelowOptionThresholds": True,
            "platformType": "ONLINE_MENU", "preOrderType": None,
        },
        "page": page_num,
        "perPage": per_page,
    }
    extensions = {"persistedQuery": {"version": 1, "sha256Hash": _DU_QUERY_HASH}}
    url = (f"{_DU_GRAPHQL}?operationName=FilteredProducts"
           f"&variables={urllib.parse.quote(json.dumps(variables))}"
           f"&extensions={urllib.parse.quote(json.dumps(extensions))}")
    r = cffi_requests.get(url, headers=_DU_HEADERS, impersonate="chrome120", timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("filteredProducts", {}).get("products", [])


def _du_all_products(dispensary_id):
    all_prods = []
    page = 0
    per_page = 100
    while True:
        batch = _du_fetch_page(dispensary_id, page, per_page)
        all_prods.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return all_prods


_DU_CANNABINOID_MAP = {
    "THCA": "thca",
    "tetrahydrocannabinolic acid": "thca",
    "CBDA": "cbda",
    "cannabidiolic acid": "cbda",
    "CBG": "cbg",
    "cannabigerol": "cbg",
    "CBN": "cbn",
    "cannabinol": "cbn",
}


def _du_potency_max(content):
    """Pull the highest non-zero value from a Dutchie ProductPotency.range."""
    rng = (content or {}).get("range") or []
    vals = [v for v in rng if isinstance(v, (int, float)) and v > 0]
    return max(vals) if vals else None


def _du_extract_cannabinoids(p):
    """Extract THC/CBD totals + minor cannabinoids from a Dutchie product."""
    out = {"thc": _du_potency_max(p.get("THCContent")),
           "cbd": _du_potency_max(p.get("CBDContent")),
           "thca": None, "cbda": None, "cbg": None, "cbn": None}
    for c in (p.get("cannabinoidsV2") or []):
        cname = (c.get("cannabinoid") or {}).get("name", "")
        val   = c.get("value")
        if val is None:
            continue
        for needle, col in _DU_CANNABINOID_MAP.items():
            if needle in cname:
                out[col] = val
                break
    # Fallback: if THCContent was empty/zero and we have THCA, use it as thc
    # (matches prior behavior — for raw flower THCA ≈ displayed potency)
    if out["thc"] is None and out["thca"] is not None:
        out["thc"] = out["thca"]
    return out


def _du_extract_price(p):
    """Safely extract the first rec price from a Dutchie product."""
    for key in ("Prices", "recPrices", "medicalPrices"):
        prices = p.get(key) or []
        if not prices:
            continue
        first = prices[0]
        if isinstance(first, (int, float)):
            return first
        if isinstance(first, dict):
            val = first.get("price")
            if val is not None:
                return val
            opts = first.get("options") or []
            if opts and isinstance(opts[0], dict):
                return opts[0].get("price")
    return None


def dutchie_search(name, dispensary_id, menu_url, strain):
    strain_words = strain.lower().split()
    matches = []
    for p in _du_all_products(dispensary_id):
        pname = p.get("Name") or p.get("name", "")
        ptype = (p.get("type") or "").lower()
        if _is_vape_category(ptype) or _is_vape_product(pname):
            continue
        if all(w in pname.lower() for w in strain_words):
            price  = _du_extract_price(p)
            cbn_data = _du_extract_cannabinoids(p)
            images = p.get("images") or []
            image_url  = images[0].get("url") if images else p.get("Image")
            created_ms = p.get("createdAt")
            try:
                from datetime import datetime as _dt
                listed_at = _dt.fromtimestamp(int(created_ms) / 1000) if created_ms else None
            except Exception:
                listed_at = None
            matches.append({
                "dispensary":   name,
                "name":         pname,
                "brand":        p.get("brandName"),
                "category":     p.get("type", "?"),
                "price":        f"${price}" if price else None,
                "url":          menu_url,
                "listed_at":    listed_at,
                "package_id":   (p.get("POSMetaData") or {}).get("canonicalPackageId"),
                "strain_type":  p.get("strainType"),
                "potency":      None,
                "thc":          cbn_data["thc"],
                "thca":         cbn_data["thca"],
                "cbd":          cbn_data["cbd"],
                "cbda":         cbn_data["cbda"],
                "cbg":          cbn_data["cbg"],
                "cbn":          cbn_data["cbn"],
                "limonene":     None,
                "beta_myrcene": None,
                "beta_caryophyllene": None,
                "humulene":     None,
                "alpha_pinene": None,
                "beta_pinene":  None,
                "linalool":     None,
                "ocimene":      None,
                "terpinolene":  None,
                "bisabolol":    None,
                "product_image": image_url,
            })
    return matches


def dutchie_list_all(name, dispensary_id, menu_url):
    products = _du_all_products(dispensary_id)
    by_type = {}
    for p in products:
        pname = (p.get("Name") or p.get("name", "")).strip()
        ptype = p.get("type", "Other")
        price = _du_extract_price(p)
        if pname:
            by_type.setdefault(ptype, []).append((pname, price))

    print(f"\n  {'─'*50}")
    print(f"  {name}  •  {menu_url}")
    print(f"  {'─'*50}")
    for cat in sorted(by_type):
        print(f"\n  [{cat}]")
        seen = set()
        for pname, price in by_type[cat]:
            if pname not in seen:
                seen.add(pname)
                print(f"    • {pname}" + (f"  —  ${price}" if price else ""))


# ══════════════════════════════════════════════════════════════════════════════
# Sweed — HTML scraper (used by Cannabist Mays Landing)
# Products are server-side-rendered into the page HTML, so we fetch and grep.
# ══════════════════════════════════════════════════════════════════════════════

# (display_name, shop_url, menu_url)
SWEED_STORES = [
    ("Cannabist ML",
     "https://www.gocannabist.com/stores/new-jersey/mays-landing/shop/recreational",
     "https://www.gocannabist.com/stores/new-jersey/mays-landing/shop/recreational"),
]


def sweed_search(name, shop_url, menu_url, strain):
    req = urllib.request.Request(shop_url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=30) as r:
        html = r.read().decode("utf-8", errors="ignore")

    strain_words = strain.lower().split()
    matches = []
    seen = set()
    # Products appear in JSON blobs embedded in the SSR HTML; find "name":"..." near "price":N
    import re as _re
    for m in _re.finditer(r'"name"\s*:\s*"([^"]{3,120})"', html):
        pname = m.group(1)
        if pname in seen:
            continue
        if _is_vape_product(pname):
            continue
        if all(w in pname.lower() for w in strain_words):
            seen.add(pname)
            # Try to find a price nearby
            chunk_after = html[m.end():m.end() + 300]
            price_m = _re.search(r'"price"\s*:\s*(\d+(?:\.\d+)?)', chunk_after)
            price = price_m.group(1) if price_m else None
            matches.append({
                "dispensary": name,
                "name": pname,
                "brand": None,
                "category": "Cannabis",
                "price": f"${price}" if price else None,
                "url": menu_url,
            })
    return matches


def sweed_list_all(name, shop_url, menu_url):
    req = urllib.request.Request(shop_url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=30) as r:
        html = r.read().decode("utf-8", errors="ignore")

    import re as _re
    print(f"\n  {'─'*50}")
    print(f"  {name}  •  {menu_url}")
    print(f"  {'─'*50}")
    seen = set()
    for m in _re.finditer(r'"name"\s*:\s*"([^"]{3,120})"', html):
        pname = m.group(1).strip()
        if pname and pname not in seen:
            seen.add(pname)
            chunk_after = html[m.end():m.end() + 300]
            price_m = _re.search(r'"price"\s*:\s*(\d+(?:\.\d+)?)', chunk_after)
            price = price_m.group(1) if price_m else None
            print(f"    • {pname}" + (f"  —  ${price}" if price else ""))


# ══════════════════════════════════════════════════════════════════════════════
# Notifications + CLI
# ══════════════════════════════════════════════════════════════════════════════

def notify_macos(title, message):
    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=True)
    except Exception:
        pass


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def check_all(strain):
    matches = []
    for store_name, venue_id, org_id, menu_url in DISPENSEAPP_STORES:
        try:
            matches += dispenseapp_search(store_name, venue_id, org_id, menu_url, strain)
        except Exception as e:
            log(f"  {store_name} error: {e}")
    for store_name, dispensary_id, menu_url in DUTCHIE_STORES:
        try:
            matches += dutchie_search(store_name, dispensary_id, menu_url, strain)
        except Exception as e:
            log(f"  {store_name} error: {e}")
    for store_name, shop_url, menu_url in SWEED_STORES:
        try:
            matches += sweed_search(store_name, shop_url, menu_url, strain)
        except Exception as e:
            log(f"  {store_name} error: {e}")
    return matches


def _canonical_strain(search_term):
    """Return the CROPS_STRAINS entry that matches the search term, or the term itself."""
    sl = search_term.lower()
    for cs in CROPS_STRAINS:
        if cs in sl:
            return cs
    return sl


def _strain_from_product_name(product_name):
    """Try to identify which known Crops strain a product name contains."""
    pn = product_name.lower()
    for cs in CROPS_STRAINS:
        if cs in pn:
            return cs
    return None


def _parse_price(price_str):
    """Convert '$12.50' or '$12' to float, or None."""
    if not price_str:
        return None
    try:
        return float(str(price_str).replace("$", "").strip())
    except ValueError:
        return None


def log_stock(matches):
    """Write results to guapa.strain_stock. Each match must have 'strain_name' set."""
    from db import get_connection
    from datetime import datetime
    now  = datetime.now()
    conn = get_connection()
    cur  = conn.cursor()
    for m in matches:
        brand = m.get("brand")
        crops_grower = 1 if brand and brand.upper() == "CROPS" else 0
        cur.execute("""
            INSERT INTO guapa.strain_stock (
                checked_at, dispensary, strain_name, brand, product_name, category,
                price, in_stock, menu_url, product_image,
                listed_at, package_id,
                strain_type, potency,
                thc, thca, cbd, cbda, cbg, cbn,
                limonene, beta_myrcene, beta_caryophyllene,
                humulene, alpha_pinene, beta_pinene,
                linalool, ocimene, terpinolene, bisabolol,
                whitelabel, crops_grower, new_batch
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, 1, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
        """, (
            now, m["dispensary"], m["strain_name"], brand, m["name"], m.get("category"),
            _parse_price(m.get("price")), m.get("url"), m.get("product_image"),
            m.get("listed_at"), m.get("package_id"),
            m.get("strain_type"), m.get("potency"),
            m.get("thc"), m.get("thca"), m.get("cbd"), m.get("cbda"),
            m.get("cbg"), m.get("cbn"),
            m.get("limonene"), m.get("beta_myrcene"), m.get("beta_caryophyllene"),
            m.get("humulene"), m.get("alpha_pinene"), m.get("beta_pinene"),
            m.get("linalool"), m.get("ocimene"), m.get("terpinolene"), m.get("bisabolol"),
            int(bool(m.get("whitelabel", False))),
            crops_grower,
            int(bool(m.get("new_batch", False))),
        ))
    conn.commit()
    cur.close()
    conn.close()


def sync_crops_catalog():
    """
    Daily sweep — logs all Crops products found across all dispensaries,
    including white-label listings under other brand names.
    Not used by the email; runs on its own schedule to build the full catalog.
    """
    seen    = set()
    deduped = []

    # Search by brand name first — these are confirmed Crops products
    for m in check_all("crops"):
        key = (m["dispensary"], m["name"])
        if key not in seen:
            seen.add(key)
            m["strain_name"] = _strain_from_product_name(m["name"]) or m["name"].lower()
            m["whitelabel"]  = False
            deduped.append(m)

    # Then sweep each known strain to catch white-label listings
    for strain_name in CROPS_STRAINS:
        for m in check_all(strain_name):
            key = (m["dispensary"], m["name"])
            if key not in seen:
                seen.add(key)
                m["strain_name"] = strain_name
                # Flag as white-label if brand isn't CROPS (or brand is missing)
                brand = (m.get("brand") or "").upper()
                m["whitelabel"] = brand != "CROPS"
                deduped.append(m)

    try:
        log_stock(deduped)
    except Exception as e:
        import traceback
        print(f"log_stock failed: {e}\n{traceback.format_exc()}")
    return deduped


def _last_package_id(dispensary, strain_name):
    """Return the most recently logged package_id for a dispensary+strain_name, or None."""
    try:
        from db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT package_id FROM guapa.strain_stock
            WHERE dispensary = %s AND strain_name = %s AND package_id IS NOT NULL
            ORDER BY checked_at DESC LIMIT 1
        """, (dispensary, strain_name))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def get_strain_stock(strain=DEFAULT_STRAIN):
    """
    Run a single check across all dispensaries, log results to DB, and return
    deduplicated matches. Intended for use by the homebase email summary.
    Each match: {dispensary, name, category, price, url, new_batch}
    """
    canonical = _canonical_strain(strain)
    matches = check_all(strain)
    seen    = set()
    deduped = []
    for m in matches:
        key = (m["dispensary"], m["name"])
        if key not in seen:
            seen.add(key)
            m["strain_name"] = canonical
            m["whitelabel"]  = (m.get("brand") or "").upper() != "CROPS"
            last_pkg = _last_package_id(m["dispensary"], canonical)
            cur_pkg  = m.get("package_id")
            m["new_batch"] = bool(cur_pkg and last_pkg and cur_pkg != last_pkg)
            deduped.append(m)
    try:
        log_stock(deduped)
    except Exception as e:
        import traceback
        print(f"log_stock failed: {e}\n{traceback.format_exc()}")
    return deduped


def main():
    parser = argparse.ArgumentParser(description="NJ dispensary strain checker")
    parser.add_argument("--strain",   default=DEFAULT_STRAIN, help="Strain name to watch")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, type=int,
                        help=f"Seconds between checks (default {DEFAULT_INTERVAL})")
    parser.add_argument("--once",     action="store_true", help="Check once and exit")
    parser.add_argument("--list",     action="store_true", help="List all products everywhere")
    args = parser.parse_args()

    if args.list:
        for store_name, venue_id, org_id, menu_url in DISPENSEAPP_STORES:
            dispenseapp_list_all(store_name, venue_id, org_id, menu_url)
        for store_name, dispensary_id, menu_url in DUTCHIE_STORES:
            dutchie_list_all(store_name, dispensary_id, menu_url)
        for store_name, shop_url, menu_url in SWEED_STORES:
            sweed_list_all(store_name, shop_url, menu_url)
        return

    strain = args.strain.strip()
    store_names = ([s[0] for s in DISPENSEAPP_STORES]
                   + [s[0] for s in DUTCHIE_STORES]
                   + [s[0] for s in SWEED_STORES])

    print()
    print("=" * 58)
    print("  NJ Dispensary — Strain Stock Checker")
    print(f"  Watching for  : {strain!r}")
    print(f"  Dispensaries  : {', '.join(store_names)}")
    if not args.once:
        print(f"  Interval      : every {args.interval}s")
    print("=" * 58)
    print()

    check = 0
    while True:
        check += 1
        log(f"Check #{check} — searching for '{strain}' ...")

        matches = check_all(strain)

        if matches:
            log(f"✅  '{strain}' IS IN STOCK!")
            seen_hits = set()
            for m in matches:
                key = (m['dispensary'], m['name'])
                if key in seen_hits:
                    continue
                seen_hits.add(key)
                price = f"  —  {m['price']}" if m['price'] else ""
                print(f"     [{m['dispensary']}]  {m['name']}{price}")
                print(f"     → {m['url']}")
            notify_macos(
                title=f"🌿 {strain} in stock!",
                message=f"Available at {', '.join(set(m['dispensary'] for m in matches))}",
            )
        else:
            log(f"❌  '{strain}' not found at any checked dispensary.")

        if args.once:
            break

        log(f"Next check in {args.interval}s ... (Ctrl+C to stop)\n")
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    main()

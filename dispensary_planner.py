"""
dispensary_planner.py — pre-trip dispensary report.

Triggered by email command "going to <dispensary>". Pulls the full flower menu
(reusing strain_sync's full-menu scraper), writes a snapshot to dispensary_menu,
then builds an HTML report with:
  - top sales right now (sorted by % off)
  - flower SKUs closest in terpene profile to a reference strain (default: Secret Meetings)

Also writes an interactive side-by-side HTML comparison to iCloud Drive
(visible on phone via Files -> iCloud Drive -> homebase).
"""
import html as html_lib
import pathlib
import re
import unicodedata
import uuid
from datetime import datetime

from db import get_connection
from strain_sync import dispenseapp_full_flower_menu, DISPENSEAPP_STORES


# Lookup: dispensary alias (lowercase) -> DISPENSEAPP_STORES tuple
def _store_for_alias(alias):
    a = alias.lower().strip()
    aliases = {
        "conservatory":   "Conservatory",
        "med leaf":       "Med Leaf",
        "medleaf":        "Med Leaf",
        "city leaves":    "City Leaves",
        "cityleaves":     "City Leaves",
        "green wellness": "Green Wellness",
    }
    target = aliases.get(a)
    if not target:
        return None
    for store in DISPENSEAPP_STORES:
        if store[0] == target:
            return store
    return None


def _safe(text):
    text = unicodedata.normalize("NFKC", str(text))
    text = html_lib.escape(text)
    return text.encode("ascii", "xmlcharrefreplace").decode("ascii")


# ── Reference profile: Secret Meetings (averaged from rows with terp data)
_SECRET_MEETINGS_REF = {
    "beta_myrcene":       0.28,
    "limonene":           0.33,
    "beta_caryophyllene": 0.31,
    "linalool":           0.10,
    "humulene":           0.07,
    "alpha_pinene":       0.03,
    "beta_pinene":        0.03,
    "terpinolene":        0.06,
    "ocimene":            0.0,
    "bisabolol":          0.0,
}
_TERP_KEYS = list(_SECRET_MEETINGS_REF.keys())


def _relative_profile(prod_or_ref):
    """Return each terpene value as a fraction of that strain's total measured terps.
    Total = sum of all terp readings (NULLs counted as 0). If total is 0, returns all 0s.
    This normalizes for "loudness" so two strains with different total terpene levels
    can be compared on profile shape alone."""
    total = sum(float(prod_or_ref.get(k) or 0) for k in _TERP_KEYS)
    if total <= 0:
        return {k: 0.0 for k in _TERP_KEYS}
    return {k: (float(prod_or_ref.get(k) or 0) / total) for k in _TERP_KEYS}


# Pre-computed relative profile for the Secret Meetings reference
_SM_RELATIVE = _relative_profile(_SECRET_MEETINGS_REF)


def classify_chemovar(prod):
    """Return a chemovar classification per Lewis (2018)-style framework.

    Returns dict with:
      type:    "I" / "II" / "III" / "IV" / "V" / None (unknown)
      cluster: "A" / "B" / "C" / None
      subtype: dominant-terpene description ("limonene-led", "balanced lim/caryo", etc.)
      label:   compact human label like "Type I / C / limonene-led"

    Type is determined by THC:CBD ratio (Type I = THC-dominant, II = mixed, III = CBD-dominant,
    IV = CBG-dominant, V = hemp/negligible cannabinoids). Cluster is the Lewis terpene cluster:
      A = myrcene + pinene dominant ("classic indica" lineages)
      B = terpinolene-dominant ("classic sativa" lineages — Jack Herer family)
      C = limonene + caryophyllene dominant (modern Cookie/Cake/Mints hybrids)
    Subtype is the single dominant terpene if its share is much higher than the next, otherwise
    a "balanced" label naming the top 2-3.
    """
    thc  = float(prod.get("thc")  or 0)
    thca = float(prod.get("thca") or 0)
    cbd  = float(prod.get("cbd")  or 0)
    cbda = float(prod.get("cbda") or 0)
    cbg  = float(prod.get("cbg")  or 0)
    # Use total THC equivalent (thc + thca*0.877 decarb factor) and total CBD equivalent
    thc_total = thc + thca * 0.877 if thca else thc
    cbd_total = cbd + cbda * 0.877 if cbda else cbd

    # Type classification
    type_label = None
    if thc_total < 1 and cbd_total < 1 and cbg < 1:
        type_label = "V"
    elif cbg > thc_total and cbg > cbd_total and cbg >= 1:
        type_label = "IV"
    elif thc_total > 0 or cbd_total > 0:
        ratio = thc_total / max(cbd_total, 0.01)
        if ratio >= 5:    type_label = "I"
        elif ratio >= 0.2: type_label = "II"
        else:              type_label = "III"

    # Cluster + subtype from relative terpene profile
    rel = _relative_profile(prod)
    cluster = None
    subtype = None
    if any(v > 0 for v in rel.values()):
        terpinolene_share = rel.get("terpinolene", 0) + rel.get("ocimene", 0)
        myrcene_pinene    = rel.get("beta_myrcene", 0) + rel.get("alpha_pinene", 0) + rel.get("beta_pinene", 0)
        limonene_caryo    = rel.get("limonene", 0) + rel.get("beta_caryophyllene", 0)
        if terpinolene_share >= 0.15:
            cluster = "B"
        elif myrcene_pinene > limonene_caryo and rel.get("beta_myrcene", 0) >= 0.30:
            cluster = "A"
        else:
            cluster = "C"

        # Subtype: find dominant terpene(s)
        ranked = sorted(rel.items(), key=lambda x: x[1], reverse=True)
        top1_key, top1_val = ranked[0]
        top2_key, top2_val = ranked[1] if len(ranked) > 1 else (None, 0)
        # Friendly names
        names = {"limonene": "lim", "beta_caryophyllene": "caryo", "beta_myrcene": "myrcene",
                 "linalool": "linalool", "humulene": "humulene", "alpha_pinene": "pinene",
                 "beta_pinene": "pinene", "terpinolene": "terp", "ocimene": "ocimene",
                 "bisabolol": "bisabolol"}
        if top1_val >= 0.40:
            subtype = f"{names.get(top1_key, top1_key)}-dominant"
        elif top1_val - top2_val <= 0.05:
            subtype = f"{names.get(top1_key, top1_key)}/{names.get(top2_key, top2_key)} balanced"
        else:
            subtype = f"{names.get(top1_key, top1_key)}-led"

    # Compact label
    parts = []
    if type_label: parts.append(f"Type {type_label}")
    if cluster:    parts.append(cluster)
    if subtype:    parts.append(subtype)
    label = " / ".join(parts) if parts else "?"

    return {"type": type_label, "cluster": cluster, "subtype": subtype, "label": label}


# Per-terpene weights for the distance metric. Terpinolene gets a 3x boost because
# it's a rare, distinctive note in Cluster C strains — Secret Meetings has 5% of its
# total terps as terpinolene, and most of its profile-shape twins have zero. Without
# weighting, the distance metric treats those zero-terpinolene strains as "close" when
# they're actually missing SM's signature whisper.
_TERP_WEIGHTS = {k: 1.0 for k in (
    "limonene", "beta_caryophyllene", "beta_myrcene", "linalool", "humulene",
    "alpha_pinene", "beta_pinene", "ocimene", "bisabolol")}
_TERP_WEIGHTS["terpinolene"] = 3.0


def _terp_distance(prod, ref):
    """Euclidean distance over RELATIVE terpene profiles (each terp as % of strain's
    own total), with terpinolene weighted 3x. This compares profile shape independent
    of overall terp loudness — a louder version of the same profile gets distance ~0,
    not penalized for being loud — but candidates missing SM's terpinolene whisper get
    penalized appropriately."""
    prod_rel = _relative_profile(prod)
    ref_rel  = _relative_profile(ref) if ref is not _SECRET_MEETINGS_REF else _SM_RELATIVE
    return sum(_TERP_WEIGHTS.get(k, 1.0) * (prod_rel[k] - ref_rel[k]) ** 2 for k in _TERP_KEYS) ** 0.5


# A "terpinolene whisper" matches SM's level: terpinolene at >= 3% of total terps
# OR >= 0.04% of bud weight. Either threshold is enough since some labs report only
# absolute percentages without computing relative shares.
def _has_terpinolene_whisper(p):
    terp_abs = (p.get("terpinolene") or 0)
    if terp_abs >= 0.04:
        return True
    rel = _relative_profile(p)
    return rel.get("terpinolene", 0) >= 0.03


# ══════════════════════════════════════════════════════════════════════════════

def snapshot_menu(dispensary_alias):
    """Pull full flower menu, write to dispensary_menu, return list of dicts + snapshot_id."""
    store = _store_for_alias(dispensary_alias)
    if not store:
        raise ValueError(f"unknown dispensary: {dispensary_alias}")
    name, venue_id, org_id, menu_url = store
    products = dispenseapp_full_flower_menu(name, venue_id, org_id, menu_url)

    snapshot_id = str(uuid.uuid4())
    now = datetime.now()
    cols = ["snapshot_id","captured_at","dispensary","brand","product_name","strain_name",
            "category","strain_type","price","sale_price","discount_pct","discount_label",
            "in_stock","package_id","menu_url",
            "thc","thca","cbd","cbda","cbg","cbn",
            "limonene","beta_myrcene","beta_caryophyllene","humulene","alpha_pinene",
            "beta_pinene","linalool","ocimene","terpinolene","bisabolol"]
    placeholders = ",".join(["%s"] * len(cols))
    sql = f"INSERT INTO dispensary_menu ({','.join(cols)}) VALUES ({placeholders})"
    rows = []
    for p in products:
        rows.append((snapshot_id, now, p["dispensary"], p.get("brand"), p["product_name"],
                     p.get("strain_name"), p.get("category"), p.get("strain_type"),
                     p.get("price"), p.get("sale_price"), p.get("discount_pct"),
                     p.get("discount_label"), p.get("in_stock", 1), p.get("package_id"),
                     p.get("menu_url"),
                     p.get("thc"), p.get("thca"), p.get("cbd"), p.get("cbda"),
                     p.get("cbg"), p.get("cbn"),
                     p.get("limonene"), p.get("beta_myrcene"), p.get("beta_caryophyllene"),
                     p.get("humulene"), p.get("alpha_pinene"), p.get("beta_pinene"),
                     p.get("linalool"), p.get("ocimene"), p.get("terpinolene"),
                     p.get("bisabolol")))
    conn = get_connection()
    cur = conn.cursor()
    cur.executemany(sql, rows)
    conn.commit()
    cur.close()
    conn.close()
    return products, snapshot_id


def find_top_sales(products, min_discount_pct=0.25, top_n=12):
    """Return products with discount >= threshold, sorted by % off desc."""
    on_sale = [p for p in products
               if p.get("discount_pct") and p["discount_pct"] >= min_discount_pct
               and p.get("in_stock")]
    on_sale.sort(key=lambda p: p["discount_pct"], reverse=True)
    return on_sale[:top_n]


def find_similar_to(products, ref=_SECRET_MEETINGS_REF, top_n=10, require_terps=True):
    """Rank flower SKUs by terpene distance to reference profile."""
    candidates = []
    for p in products:
        if not p.get("in_stock"):
            continue
        if require_terps and not p.get("beta_myrcene"):
            continue
        # Skip pre-rolls and concentrates from similarity ranking — flower-only signal
        cat = (p.get("category") or "").lower()
        if "pre-roll" in cat or "preroll" in cat:
            continue
        d = _terp_distance(p, ref)
        candidates.append((d, p))
    candidates.sort(key=lambda x: x[0])
    return candidates[:top_n]


# ══════════════════════════════════════════════════════════════════════════════
# HTML email body

_GUAPA_NAV = (
    '<div style="background:#0a0a0a;color:#f0c014;padding:14px 28px;'
    'font-family:Helvetica,Arial,sans-serif;font-size:13px;letter-spacing:1px;'
    'display:flex;justify-content:space-between;">'
    '<span><b>GUAPA inc</b></span><span>homebase</span></div>'
)


def _fmt_price(p):
    if p is None: return "&mdash;"
    if p == int(p): return f"${int(p)}"
    return f"${p:.2f}"


def _row_sale(p):
    pct = int(round((p.get("discount_pct") or 0) * 100))
    name = _safe(p["product_name"])
    brand = _safe(p.get("brand") or "")
    return (f'<tr><td style="padding:6px 8px;font-size:12px;">{brand}</td>'
            f'<td style="padding:6px 8px;font-size:12px;">{name}</td>'
            f'<td style="padding:6px 8px;font-size:12px;text-align:right;'
            f'color:#888;text-decoration:line-through;">{_fmt_price(p.get("price"))}</td>'
            f'<td style="padding:6px 8px;font-size:12px;text-align:right;'
            f'color:#7ec89b;font-weight:bold;">{_fmt_price(p.get("sale_price"))}</td>'
            f'<td style="padding:6px 8px;font-size:12px;text-align:right;'
            f'color:#f0c014;">{pct}% off</td></tr>')


def _row_similar(distance, p):
    name = _safe(p["product_name"])
    brand = _safe(p.get("brand") or "")
    thc = p.get("thc")
    thc_str = f"{thc:.0f}%" if thc else "&mdash;"
    price = _fmt_price(p.get("sale_price") or p.get("price"))
    # Top-3 terpene tags
    terps = sorted([(k, p.get(k) or 0) for k in _TERP_KEYS], key=lambda x: x[1], reverse=True)[:3]
    terp_label = " &middot; ".join(f"{k.replace('beta_','').replace('alpha_','')[:4]} {v:.2f}"
                                   for k, v in terps if v > 0)
    return (f'<tr><td style="padding:6px 8px;font-size:12px;">{brand}</td>'
            f'<td style="padding:6px 8px;font-size:12px;">{name}</td>'
            f'<td style="padding:6px 8px;font-size:12px;text-align:right;">{thc_str}</td>'
            f'<td style="padding:6px 8px;font-size:12px;text-align:right;">{price}</td>'
            f'<td style="padding:6px 8px;font-size:11px;color:#888;">{_safe(terp_label)}</td>'
            f'<td style="padding:6px 8px;font-size:11px;text-align:right;color:#888;">'
            f'{distance:.2f}</td></tr>')


def build_trip_email(dispensary_alias):
    """Returns {'text': ..., 'html': ...} for emailer.send_email."""
    store = _store_for_alias(dispensary_alias)
    if not store:
        return {"text": f"Don't know that dispensary: {dispensary_alias}",
                "html": f"<p>Don't know that dispensary: {_safe(dispensary_alias)}</p>"}

    products, snapshot_id = snapshot_menu(dispensary_alias)
    name = store[0]
    sales   = find_top_sales(products)
    similar = find_similar_to(products)

    # ── HTML body ─────────────────────────────────────────────────────────────
    parts = [_GUAPA_NAV,
             f'<div style="max-width:640px;margin:0 auto;padding:20px 28px;'
             f'font-family:Helvetica,Arial,sans-serif;color:#222;">']
    parts.append(f'<h2 style="margin:8px 0 4px;">Heading to {_safe(name)}</h2>')
    parts.append(f'<div style="font-size:12px;color:#888;margin-bottom:18px;">'
                 f'{len(products)} flower/pre-roll SKUs &middot; '
                 f'{sum(1 for p in products if p.get("beta_myrcene"))} with terpene data</div>')

    # Sales section
    parts.append('<h3 style="margin:18px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px;">'
                 'Top sales right now</h3>')
    if sales:
        parts.append('<table style="width:100%;border-collapse:collapse;">')
        parts.append('<tr style="background:#f7f7f7;font-size:11px;color:#666;">'
                     '<th style="padding:6px 8px;text-align:left;">Brand</th>'
                     '<th style="padding:6px 8px;text-align:left;">Product</th>'
                     '<th style="padding:6px 8px;text-align:right;">Was</th>'
                     '<th style="padding:6px 8px;text-align:right;">Now</th>'
                     '<th style="padding:6px 8px;text-align:right;">Off</th></tr>')
        for p in sales:
            parts.append(_row_sale(p))
        parts.append('</table>')
    else:
        parts.append('<p style="font-size:12px;color:#888;">Nothing >25% off in stock.</p>')

    # Similar-to-Secret-Meetings section
    parts.append('<h3 style="margin:24px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px;">'
                 'Closest to Secret Meetings (by terpenes)</h3>')
    parts.append('<div style="font-size:11px;color:#888;margin-bottom:6px;">'
                 'Reference: limonene 0.33, caryophyllene 0.31, myrcene 0.28, linalool 0.10. '
                 'Flower only, pre-rolls excluded. Lower distance = closer match.</div>')
    if similar:
        parts.append('<table style="width:100%;border-collapse:collapse;">')
        parts.append('<tr style="background:#f7f7f7;font-size:11px;color:#666;">'
                     '<th style="padding:6px 8px;text-align:left;">Brand</th>'
                     '<th style="padding:6px 8px;text-align:left;">Product</th>'
                     '<th style="padding:6px 8px;text-align:right;">THC</th>'
                     '<th style="padding:6px 8px;text-align:right;">Price</th>'
                     '<th style="padding:6px 8px;text-align:left;">Top terps</th>'
                     '<th style="padding:6px 8px;text-align:right;">Dist</th></tr>')
        for d, p in similar:
            parts.append(_row_similar(d, p))
        parts.append('</table>')
    else:
        parts.append('<p style="font-size:12px;color:#888;">No flower with terpene data right now.</p>')

    parts.append('</div>')
    html_body = "".join(parts)

    # Side-effect: refresh ALL tracked stores so the side-by-side comparison HTML
    # has live data for every section, not just the one the email was about.
    try:
        for other in ("Conservatory", "Med Leaf"):
            if other == name:
                continue
            try:
                snapshot_menu(other.lower())  # lowered display name doubles as a valid alias
            except Exception as e:
                # If a refresh fails, fall back to the latest stored snapshot in DB.
                print(f"[dispensary_planner] refresh of {other} failed: {e}")
        write_comparison_html(products, name)
    except Exception as e:
        # Don't fail the trip email if the comparison artifact has issues
        print(f"[dispensary_planner] comparison html failed: {e}")

    # ── Plain-text fallback ───────────────────────────────────────────────────
    txt = [f"Heading to {name} - {len(products)} SKUs"]
    txt.append("")
    txt.append("TOP SALES:")
    for p in sales[:8]:
        pct = int(round((p.get("discount_pct") or 0) * 100))
        txt.append(f"  {pct}% off  {p.get('brand') or '?':<20} {p['product_name'][:50]}  "
                   f"${p.get('price')} -> ${p.get('sale_price')}")
    txt.append("")
    txt.append("CLOSEST TO SECRET MEETINGS:")
    for d, p in similar[:8]:
        txt.append(f"  dist={d:.2f}  {p.get('brand') or '?':<20} {p['product_name'][:50]}  "
                   f"thc={p.get('thc')} ${p.get('sale_price') or p.get('price')}")
    return {"text": "\n".join(txt), "html": html_body}


# ══════════════════════════════════════════════════════════════════════════════
# Side-by-side comparison HTML (saved to iCloud + logs)

# Display label per terpene key. Use a dict so labels can never drift out of order
# from _TERP_KEYS (a previous bug had them reversed for myrcene/limonene/caryophyllene
# because two parallel lists got desynced; never let that happen again).
_TERP_DISPLAY = {
    "beta_myrcene":       "Myrcene",
    "limonene":           "Limonene",
    "beta_caryophyllene": "Caryophyllene",
    "linalool":           "Linalool",
    "humulene":           "Humulene",
    "alpha_pinene":       "a-Pinene",
    "beta_pinene":        "b-Pinene",
    "terpinolene":        "Terpinolene",
    "ocimene":            "Ocimene",
    "bisabolol":          "Bisabolol",
}
_TERP_LABELS = [_TERP_DISPLAY[k] for k in _TERP_KEYS]  # ordered to match keys


def _grams_from_name(name):
    if not name: return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[gG]\b", name)
    return float(m.group(1)) if m else None


_NON_STRAIN_TOKENS = re.compile(
    r"^\s*(\d+(?:\.\d+)?\s*(g|oz|mg|gram|ounce)|"
    r"flower|pre-?roll|pre-?rolls|small\s*buds?|premium|trim|"
    r"infused|live|kief|diamond|hash|concentrate|cartridge|vape|disposable|"
    r"-)\s*$",
    re.IGNORECASE,
)


_SIZE_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?\s*[gG]\b")


def _strain_label_from_product(product_name, brand):
    """Pick the segment most likely to be the strain name across naming conventions:
      Conservatory:        BRAND | STRAIN | SIZE
      Med Leaf:            STRAIN | SIZE | CATEGORY
      Harvest Moon Farms:  SUB-BRAND | STRAIN | SIZE  (e.g. "MADE | BERRY KIMBER OG | - 3.5 G")
      Magic Garden:        BRAND | SUB-BRAND | STRAIN | SIZE
    Strategy: filter out brand, size descriptors, and pure category tokens, then return the
    longest surviving segment (sub-brands tend to be short, strain names tend to be longer)."""
    if not product_name:
        return ""
    segs = [s.strip() for s in product_name.split("|") if s.strip()]
    if not segs:
        return product_name
    brand_norm = (brand or "").strip().lower()

    candidates = []
    for seg in segs:
        if seg.lower() == brand_norm:
            continue
        if _SIZE_TOKEN_RE.search(seg):  # contains "X G" / "3.5 G" / etc.
            continue
        if _NON_STRAIN_TOKENS.match(seg):  # pure size / category tokens
            continue
        candidates.append(seg)

    if candidates:
        return max(candidates, key=len)
    # Fallback: first non-brand segment, else first segment
    for seg in segs:
        if seg.lower() != brand_norm:
            return seg
    return segs[0]


def _classify_cell(ref_rel, candidate_rel, candidate_raw, ref_raw,
                   rel_thresh=0.40, abs_thresh=0.04):
    """Operates on RELATIVE profiles (% of strain's own total terps). 'missing' state
    still triggers when the candidate's raw value is null but the reference has a
    meaningful raw value (>=0.05% of bud weight). 'drastic' = relative-share differs
    by >=40% AND >=0.04 absolute share (e.g., 27% of total vs 17% of total)."""
    if candidate_raw is None:
        if ref_raw and ref_raw >= 0.05:
            return "missing"
        return "ok"
    if not ref_rel:
        return "ok"
    abs_diff = abs(candidate_rel - ref_rel)
    if abs_diff < abs_thresh or (abs_diff / ref_rel) < rel_thresh:
        return "ok"
    return "high" if candidate_rel > ref_rel else "low"


def _is_clone(col, ref_dict, tol=0.04):
    """Every measured terp's RELATIVE share is within `tol` of reference's relative share;
    missing values for ref-significant terps fail. Default 0.04 in relative-share space:
    e.g. limonene at 27% vs 31% of total = 4-point gap. Calibrated for normalized profile
    matching after switching from absolute to relative comparison 5/03."""
    ref_rel = _relative_profile(ref_dict)
    cand_rel = _relative_profile(col)
    for k in _TERP_KEYS:
        ref_raw = ref_dict.get(k, 0) or 0
        if col.get(k) is None and ref_raw >= 0.05:
            return False
        if abs(cand_rel[k] - ref_rel[k]) > tol:
            return False
    return True


_CELL_STYLE = {
    "ok":      "",
    "high":    "background:#ffd6d6;color:#a02525;",
    "low":     "background:#fff0c2;color:#8b6a00;",
    "missing": "background:#f0f0f0;color:#999;font-style:italic;",
}


_HTML_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Secret Meetings - Side by Side</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; background: #fafafa; color: #222; padding: 16px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  h2.store { font-size: 16px; margin: 28px 0 4px; padding-top: 18px; border-top: 1px solid #ddd; }
  h2.store:first-of-type { border-top: none; padding-top: 0; }
  .sub { color: #888; font-size: 12px; margin-bottom: 16px; }
  /* Scroll container — explicit width so sticky cols compute against a known viewport.
     -webkit-overflow-scrolling enables momentum scrolling on iOS Safari. */
  .scroll {
    width: 100%;
    overflow-x: scroll;
    -webkit-overflow-scrolling: touch;
    border: 1px solid #ddd;
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    margin-bottom: 8px;
  }
  /* Force the table to size to its content, never narrower than the scroll viewport.
     Without this, sticky columns can mis-position in some browsers. */
  table { border-collapse: separate; border-spacing: 0; font-size: 13px; width: max-content; min-width: 100%; }
  thead th { background:#f0f0f0; padding:10px 12px; text-align:left; font-weight:600;
             border-bottom:2px solid #ccc; white-space:nowrap; }
  tbody td { white-space:nowrap; padding:8px 12px; border-bottom:1px solid #eee; }
  /* Frozen first column */
  th.sticky-l, td.sticky-l {
    position: sticky; left: 0;
    background: #fff;
    font-weight: 600; min-width: 130px; max-width: 130px;
    box-shadow: 1px 0 0 #ddd;
    z-index: 3;
  }
  thead th.sticky-l { background: #f0f0f0; z-index: 4; }
  /* Frozen second column (reference) — pinned right after sticky-l */
  th.sticky-r, td.sticky-r {
    position: sticky; left: 130px;
    background: #fff8d6;
    font-weight: 600; min-width: 160px; max-width: 160px;
    box-shadow: 1px 0 0 #d4c98a;
    z-index: 3;
  }
  thead th.sticky-r { background: #f5e9aa; z-index: 4; }
  .header-row td { background:#fafafa; font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px; }
  .legend { font-size:11px; color:#666; margin: 12px 0 28px; display:flex; gap:14px; flex-wrap:wrap; }
  .legend span { padding:2px 8px; border-radius:3px; }
  .legend .clone { background:#d6f5dc; color:#2a8a3e; font-weight:600; }
  .legend .high { background:#ffd6d6; color:#a02525; }
  .legend .low  { background:#fff0c2; color:#8b6a00; }
  .legend .miss { background:#f0f0f0; color:#999; font-style:italic; }
  td.exact, th.exact { background:#d6f5dc !important; }
  th.exact { color:#1f5e2c; }
  .empty { color: #999; font-style: italic; padding: 14px 0; font-size: 13px; }
  /* Spacer column at the end — gives natural breathing room when scrolled all the way right */
  td.tail-spacer, th.tail-spacer { min-width: 16px; padding: 0; border: none; background: transparent; }

  /* ── Mobile / narrow viewport (iPhone portrait, etc.) ──
     Sticky columns at desktop sizes (130 + 160 = 290px) consume almost the entire iPhone
     portrait viewport, leaving the candidate columns unreadably narrow. Compress everything. */
  @media (max-width: 600px) {
    body { padding: 8px; }
    h1 { font-size: 16px; }
    h2.store { font-size: 14px; margin: 18px 0 4px; padding-top: 12px; }
    .sub, .legend { font-size: 10px; }
    table { font-size: 11px; }
    thead th { padding: 6px 7px; }
    tbody td { padding: 5px 7px; }
    th.sticky-l, td.sticky-l { min-width: 84px; max-width: 84px; }
    th.sticky-r, td.sticky-r { left: 84px; min-width: 96px; max-width: 96px; }
    /* Wrap long strain names in headers so they fit two lines instead of forcing horizontal scroll */
    thead th { white-space: normal; line-height: 1.2; }
    tbody td { white-space: normal; }
    /* But keep numeric cells single-line so they don't wrap awkwardly */
    tbody td:not(.sticky-l):not(.sticky-r) { white-space: nowrap; }
  }
</style></head><body>"""


def _render_store_section(products, dispensary_name, ref, ref_label, ref_thc, top_n):
    """Return the HTML fragment for one store's comparison table (no document chrome)."""
    if not products:
        return (f'<h2 class="store">{html_lib.escape(dispensary_name)}</h2>'
                f'<div class="empty">No snapshot for {html_lib.escape(dispensary_name)} yet '
                f'&mdash; email "going to {dispensary_name.lower()}" to capture one.</div>')

    similar = find_similar_to(products, ref=ref, top_n=top_n)
    if not similar:
        return (f'<h2 class="store">{html_lib.escape(dispensary_name)}</h2>'
                f'<div class="empty">No flower with terpene data in the latest {html_lib.escape(dispensary_name)} snapshot.</div>')

    cols = [{"label": ref_label, "brand": "Crops", "thc": ref_thc, "thca": ref_thc,
             "cbd": 0, "cbg": 0,
             "price": None, "grams": None, "ppg": None, "dist": 0.0,
             **{k: ref[k] for k in ref}}]
    for d, p in similar:
        name = (p.get("product_name") or "")
        short = _strain_label_from_product(name, p.get("brand"))
        grams = _grams_from_name(name)
        price = p.get("sale_price") or p.get("price")
        cols.append({
            "label": short[:24], "brand": p.get("brand") or "?",
            "thc": p.get("thc"), "price": price, "grams": grams,
            "ppg": (price/grams) if (price and grams) else None, "dist": d,
            **{k: p.get(k) for k in ref},
        })

    # Compute totals (absolute % bud weight) and relative profiles (each terp / total)
    for c in cols:
        c["_total_terps"] = sum((c.get(k) or 0) for k in _TERP_KEYS)
        c["_relative"]    = _relative_profile(c)
        c["_chemovar"]    = classify_chemovar(c)
        c["_whisper"]     = _has_terpinolene_whisper(c)

    exact_idx = {i for i, c in enumerate(cols[1:], start=1) if _is_clone(c, ref)}

    parts = [f'<h2 class="store">{html_lib.escape(dispensary_name)} &mdash; '
             f'{len(products)} SKUs in latest snapshot</h2>',
             '<div class="scroll"><table><thead><tr>',
             '<th class="sticky-l">Field</th>',
             f'<th class="sticky-r">{html_lib.escape(cols[0]["label"])}</th>']
    for i, c in enumerate(cols[1:], start=1):
        if i in exact_idx:
            parts.append(f'<th class="exact">{html_lib.escape(c["label"])} <span style="color:#2a8a3e;">&#10003; clone</span></th>')
        else:
            parts.append(f'<th>{html_lib.escape(c["label"])}</th>')
    parts.append('<th class="tail-spacer"></th></tr></thead><tbody>')

    def _row(label, key, fmtfn):
        row = ['<tr>',
               f'<td class="sticky-l">{html_lib.escape(label)}</td>',
               f'<td class="sticky-r">{fmtfn(cols[0].get(key))}</td>']
        for i, c in enumerate(cols[1:], start=1):
            cls = ' class="exact"' if i in exact_idx else ''
            row.append(f'<td{cls}>{fmtfn(c.get(key))}</td>')
        row.append('<td class="tail-spacer"></td></tr>')
        parts.append("".join(row))

    _row("Brand", "brand", lambda v: html_lib.escape(v) if v else "&mdash;")
    _row("Size", "grams", lambda v: f"{v}g" if v else "&mdash;")
    _row("Price", "price", lambda v: f"${v:.0f}" if v else "&mdash;")
    _row("Price / gram", "ppg", lambda v: f"<b>${v:.2f}/g</b>" if v else "&mdash;")
    _row("THC %", "thc", lambda v: f"{v:.1f}%" if v else "&mdash;")
    _row("Distance to ref", "dist", lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "&mdash;")
    _row("Total terpenes", "_total_terps", lambda v: f"<b>{v:.2f}%</b>" if v else "&mdash;")

    # Chemovar row — show full label for the reference column, but for candidates compress to just
    # the differing pieces. If Type AND Cluster match ref, show only the subtype. If only Cluster
    # differs, show Cluster + subtype. If Type differs, show the whole label (rare in NJ rec).
    ref_chem = cols[0].get("_chemovar") or {}
    def _chemovar_short(v):
        if not isinstance(v, dict):
            return "&mdash;"
        if v is ref_chem:  # reference column itself — show the full label
            return html_lib.escape(v.get("label", "?"))
        type_diff    = v.get("type")    != ref_chem.get("type")
        cluster_diff = v.get("cluster") != ref_chem.get("cluster")
        subtype = v.get("subtype") or "?"
        if type_diff:
            return html_lib.escape(v.get("label", "?"))
        if cluster_diff:
            cl = v.get("cluster") or "?"
            return html_lib.escape(f"{cl} / {subtype}")
        return html_lib.escape(subtype)
    _row("Chemovar", "_chemovar", _chemovar_short)
    # Terpinolene whisper indicator — surfaces SM's distinguishing trait.
    # The reference column always shows ✓ (SM has it by definition).
    _row("Terp whisper", "_whisper",
         lambda v: ('<span style="color:#2a8a3e;font-weight:600;">&#10003; yes</span>'
                    if v else '<span style="color:#999;">&mdash;</span>'))

    parts.append('<tr class="header-row"><td class="sticky-l">&mdash; Terpenes (% of strain\'s total terps) &mdash;</td>'
                 f'<td class="sticky-r"></td>{"<td></td>"*(len(cols)-1)}<td class="tail-spacer"></td></tr>')

    ref_rel = cols[0]["_relative"]
    for k, lbl in zip(_TERP_KEYS, _TERP_LABELS):
        ref_raw = cols[0].get(k)
        ref_share = ref_rel.get(k, 0)
        # Display reference column as relative share, formatted as percentage
        ref_str = f"{ref_share*100:.0f}%" if ref_share else "&mdash;"
        row = ['<tr>',
               f'<td class="sticky-l">{html_lib.escape(lbl)}</td>',
               f'<td class="sticky-r">{ref_str}</td>']
        for i, c in enumerate(cols[1:], start=1):
            cv_raw = c.get(k)
            cv_rel = c["_relative"].get(k, 0)
            state = _classify_cell(ref_share, cv_rel, cv_raw, ref_raw)
            style = _CELL_STYLE[state]
            cls = ' class="exact"' if i in exact_idx else ''
            txt = f"{cv_rel*100:.0f}%" if cv_raw is not None else "&mdash;"
            row.append(f'<td{cls} style="{style}">{txt}</td>')
        row.append('<td class="tail-spacer"></td></tr>')
        parts.append("".join(row))

    parts.append('</tbody></table></div>')

    # ── "Notable cousins" — limonene-rich AND loud terpinolene (>= 0.10% absolute).
    # Not SM clones, but if you like SM's small terpinolene whisper, these turn it up
    # to 11. Different feel from SM (more cerebral / old-school sativa edge), but
    # related family.
    cousins = _find_loud_terp_cousins(products, top_n=4)
    if cousins:
        parts.append('<h3 style="font-size:13px;margin:12px 0 4px;color:#444;">'
                     'Loud-terpinolene cousins (different feel, but related)</h3>')
        parts.append('<div class="sub" style="margin-bottom:6px;">'
                     'These are limonene-rich AND have much louder terpinolene than SM '
                     '(0.10%+ vs SM\'s 0.06%). Expect a more cerebral / piney / old-school '
                     'sativa edge. Pick for variety, not for matching SM\'s vibe.</div>')
        parts.append('<div class="scroll"><table><thead><tr>'
                     '<th>Strain</th><th>Brand</th><th>Size</th><th>Price</th>'
                     '<th>Total terps</th><th>Terpinolene</th><th>Limonene</th>'
                     '<th>Chemovar</th></tr></thead><tbody>')
        for p in cousins:
            name  = _strain_label_from_product(p.get("product_name"), p.get("brand"))
            grams = _grams_from_name(p.get("product_name") or "")
            price = p.get("sale_price") or p.get("price")
            total = sum((p.get(k) or 0) for k in _TERP_KEYS)
            cv    = classify_chemovar(p)
            parts.append(
                f'<tr><td>{html_lib.escape(name[:30])}</td>'
                f'<td>{html_lib.escape((p.get("brand") or "?")[:18])}</td>'
                f'<td>{f"{grams}g" if grams else "&mdash;"}</td>'
                f'<td>{f"${price:.0f}" if price else "&mdash;"}</td>'
                f'<td><b>{total:.2f}%</b></td>'
                f'<td style="color:#2a8a3e;font-weight:600;">{p["terpinolene"]:.2f}%</td>'
                f'<td>{(p.get("limonene") or 0):.2f}%</td>'
                f'<td>{html_lib.escape(cv["label"])}</td></tr>'
            )
        parts.append('</tbody></table></div>')

    return "".join(parts)


def _find_loud_terp_cousins(products, top_n=4, min_lim=0.20, min_terp=0.10):
    """Return limonene-rich, loud-terpinolene strains (different feel from SM but related).
    Filters to flower only (no pre-rolls), in stock, with both terps measured."""
    out = []
    for p in products:
        if not p.get("in_stock"):
            continue
        cat = (p.get("category") or "").lower()
        if "pre-roll" in cat or "preroll" in cat:
            continue
        lim  = p.get("limonene") or 0
        terp = p.get("terpinolene") or 0
        if lim >= min_lim and terp >= min_terp:
            out.append(p)
    out.sort(key=lambda p: (p.get("terpinolene") or 0), reverse=True)
    return out[:top_n]


def _latest_snapshot_for(dispensary_name):
    """Pull the latest snapshot from dispensary_menu for a given store name.
    Returns list of dicts with Decimal values converted to float."""
    import decimal
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""SELECT * FROM dispensary_menu
                   WHERE dispensary=%s
                     AND snapshot_id=(SELECT snapshot_id FROM dispensary_menu
                                      WHERE dispensary=%s
                                      ORDER BY captured_at DESC LIMIT 1)""",
                (dispensary_name, dispensary_name))
    rows = cur.fetchall()
    cur.close(); conn.close()
    for p in rows:
        for k, v in list(p.items()):
            if isinstance(v, decimal.Decimal):
                p[k] = float(v)
    return rows


def write_comparison_html(products=None, dispensary_name=None, ref=_SECRET_MEETINGS_REF,
                          ref_label="Secret Meetings (ref)", ref_thc=28.6, top_n=6,
                          stores_to_show=("Conservatory", "Med Leaf"),
                          icloud_dir=r"C:\Users\eewil\iCloudDrive\homebase",
                          local_path="logs/secret_meetings_compare.html"):
    """Build a freeze-pane HTML with one section per store and write to iCloud + logs.

    Always renders every store in `stores_to_show` so the user gets both views regardless of
    which one triggered the refresh. The freshly-captured (products, dispensary_name) pair is
    used for that store's section; other stores are loaded from the latest DB snapshot.

    Backward compat: passing just (products, dispensary_name) still works.
    """
    parts = [_HTML_HEAD,
             '<h1>Secret Meetings &mdash; closest matches by terpene profile</h1>',
             '<div class="sub">Each terpene cell shows that terpene\'s <b>share of the strain\'s total terpenes</b> (e.g. "27%" means 27% of all this strain\'s terps are limonene). This normalizes for "loudness" so two strains with different total terpene levels can be compared on profile shape alone. The "Total terpenes" row shows absolute loudness (% of dry bud weight). Cells highlighted when relative share differs from Secret Meetings by &ge;40% AND &ge;4 percentage points. <b>Green column</b> = profile clone (every measured terp share within 4 points of reference).</div>',
             '<div class="legend">'
             '<span class="clone">green column = profile clone</span>'
             '<span class="high">red = way more than ref share</span>'
             '<span class="low">amber = way less than ref share</span>'
             '<span class="miss">gray = lab did not report it</span>'
             '</div>']

    for store in stores_to_show:
        if products is not None and dispensary_name == store:
            store_products = products
        else:
            store_products = _latest_snapshot_for(store)
        parts.append(_render_store_section(store_products, store, ref,
                                            ref_label, ref_thc, top_n))

    parts.append(f'<div class="sub" style="margin-top:24px;">Generated {datetime.now().strftime("%a %b %d %Y, %I:%M %p")}.</div>')
    parts.append('</body></html>')

    body = "".join(parts)
    paths = {}
    if local_path:
        local = pathlib.Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(body, encoding="utf-8")
        paths["local"] = str(local.resolve())
    if icloud_dir:
        ic = pathlib.Path(icloud_dir)
        ic.mkdir(parents=True, exist_ok=True)
        ic_path = ic / "secret_meetings_compare.html"
        ic_path.write_text(body, encoding="utf-8")
        paths["icloud"] = str(ic_path)
    return paths

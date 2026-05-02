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


def _terp_distance(prod, ref):
    """Euclidean distance over terpene profile. NULLs treated as 0."""
    return sum((float(prod.get(k) or 0) - ref[k]) ** 2 for k in _TERP_KEYS) ** 0.5


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

    # Side-effect: refresh the side-by-side comparison HTML at iCloud + logs
    try:
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

_TERP_LABELS = ["Limonene", "Caryophyllene", "Myrcene", "Linalool", "Humulene",
                "a-Pinene", "b-Pinene", "Terpinolene", "Ocimene", "Bisabolol"]


def _grams_from_name(name):
    if not name: return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[gG]\b", name)
    return float(m.group(1)) if m else None


def _classify_cell(ref_val, candidate_val, rel_thresh=0.40, abs_thresh=0.05):
    """Drastic = relative diff >= rel_thresh AND absolute diff >= abs_thresh."""
    if candidate_val is None:
        if ref_val and ref_val >= 0.05:
            return "missing"
        return "ok"
    if ref_val is None or ref_val == 0:
        return "ok"
    abs_diff = abs(candidate_val - ref_val)
    if abs_diff < abs_thresh or (abs_diff / ref_val) < rel_thresh:
        return "ok"
    return "high" if candidate_val > ref_val else "low"


def _is_clone(col, ref_dict, tol=0.05):
    """Every measured terp within `tol` of reference; missing values for ref-significant terps fail.
    Default 0.05: tight enough that only genuine batch-twins of the reference qualify (e.g. the
    same strain rebranded), but loose enough to absorb normal lab-to-lab variation. Calibrated
    against Med Leaf 5/02 — 0.10 over-fires, 0.01-0.03 reject even the literal SM."""
    for k in _TERP_KEYS:
        ref_v = ref_dict.get(k, 0) or 0
        cand_v = col.get(k)
        if cand_v is None:
            if ref_v >= 0.05:
                return False
            continue
        if abs(cand_v - ref_v) > tol:
            return False
    return True


_CELL_STYLE = {
    "ok":      "",
    "high":    "background:#ffd6d6;color:#a02525;",
    "low":     "background:#fff0c2;color:#8b6a00;",
    "missing": "background:#f0f0f0;color:#999;font-style:italic;",
}


def write_comparison_html(products, dispensary_name, ref=_SECRET_MEETINGS_REF,
                          ref_label="Secret Meetings (ref)", ref_thc=28.6, top_n=6,
                          icloud_dir=r"C:\Users\eewil\iCloudDrive\homebase",
                          local_path="logs/secret_meetings_compare.html"):
    """Build the freeze-pane side-by-side HTML and write it to iCloud + logs.
    Returns dict with paths. Called automatically from build_trip_email()."""
    similar = find_similar_to(products, ref=ref, top_n=top_n)

    cols = [{"label": ref_label, "brand": "Crops", "thc": ref_thc,
             "price": None, "grams": None, "ppg": None, "dist": 0.0,
             **{k: ref[k] for k in ref}}]
    for d, p in similar:
        name = (p.get("product_name") or "")
        short = name.split("|")[1].strip() if "|" in name else name
        grams = _grams_from_name(name)
        price = p.get("sale_price") or p.get("price")
        cols.append({
            "label": short[:24], "brand": p.get("brand") or "?",
            "thc": p.get("thc"), "price": price, "grams": grams,
            "ppg": (price/grams) if (price and grams) else None, "dist": d,
            **{k: p.get(k) for k in ref},
        })

    exact_idx = {i for i, c in enumerate(cols[1:], start=1) if _is_clone(c, ref)}

    parts = ['<!DOCTYPE html><html><head><meta charset="utf-8">'
             f'<title>{html_lib.escape(ref_label)} - Side by Side</title>',
             '''<style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; background: #fafafa; margin: 0; padding: 24px; color: #222; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #888; font-size: 12px; margin-bottom: 16px; }
  .scroll { overflow-x: auto; border: 1px solid #ddd; border-radius: 8px; background: #fff; max-width:100%; box-shadow:0 1px 3px rgba(0,0,0,0.04); }
  table { border-collapse: collapse; font-size: 13px; }
  thead th { background:#f0f0f0; padding:10px 12px; text-align:left; font-weight:600;
             border-bottom:2px solid #ccc; position:sticky; top:0; z-index:2; white-space:nowrap; }
  tbody td { white-space:nowrap; padding:8px 12px; border-bottom:1px solid #eee; }
  th.sticky-l, td.sticky-l { position:sticky; left:0; background:#fff; z-index:3;
                              font-weight:600; min-width:130px; box-shadow:1px 0 0 #ddd; }
  thead th.sticky-l { z-index:4; background:#f0f0f0; }
  th.sticky-r, td.sticky-r { position:sticky; left:130px; background:#fff8d6; z-index:3;
                              font-weight:600; min-width:160px; box-shadow:1px 0 0 #d4c98a; }
  thead th.sticky-r { z-index:4; background:#f5e9aa; }
  .header-row td { background:#fafafa; font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px; }
  .legend { font-size:11px; color:#666; margin-top:12px; display:flex; gap:14px; flex-wrap:wrap; }
  .legend span { padding:2px 8px; border-radius:3px; }
  .legend .clone { background:#d6f5dc; color:#2a8a3e; font-weight:600; }
  .legend .high { background:#ffd6d6; color:#a02525; }
  .legend .low  { background:#fff0c2; color:#8b6a00; }
  .legend .miss { background:#f0f0f0; color:#999; font-style:italic; }
  td.exact, th.exact { background:#d6f5dc !important; }
  th.exact { color:#1f5e2c; }
</style></head><body>''']
    parts.append(f'<h1>{html_lib.escape(ref_label.split(" (")[0])} &mdash; closest matches at {html_lib.escape(dispensary_name)}</h1>')
    parts.append('<div class="sub">Reference column is frozen on the left. Terpene cells are highlighted when they differ by &ge;40% AND &ge;0.05 absolute. Gray = lab did not report. <b>Green column</b> = profile clone (every measured terp within 0.05 of reference - same strain or genuine batch-twin).</div>')
    parts.append('<div class="scroll"><table><thead><tr>')
    parts.append('<th class="sticky-l">Field</th>')
    parts.append(f'<th class="sticky-r">{html_lib.escape(cols[0]["label"])}</th>')
    for i, c in enumerate(cols[1:], start=1):
        if i in exact_idx:
            parts.append(f'<th class="exact">{html_lib.escape(c["label"])} <span style="color:#2a8a3e;">&#10003; clone</span></th>')
        else:
            parts.append(f'<th>{html_lib.escape(c["label"])}</th>')
    parts.append('</tr></thead><tbody>')

    def _row(label, key, fmtfn):
        row = ['<tr>',
               f'<td class="sticky-l">{html_lib.escape(label)}</td>',
               f'<td class="sticky-r">{fmtfn(cols[0].get(key))}</td>']
        for i, c in enumerate(cols[1:], start=1):
            cls = ' class="exact"' if i in exact_idx else ''
            row.append(f'<td{cls}>{fmtfn(c.get(key))}</td>')
        row.append('</tr>')
        parts.append("".join(row))

    _row("Brand", "brand", lambda v: html_lib.escape(v) if v else "&mdash;")
    _row("Size", "grams", lambda v: f"{v}g" if v else "&mdash;")
    _row("Price", "price", lambda v: f"${v:.0f}" if v else "&mdash;")
    _row("Price / gram", "ppg", lambda v: f"<b>${v:.2f}/g</b>" if v else "&mdash;")
    _row("THC %", "thc", lambda v: f"{v:.1f}%" if v else "&mdash;")
    _row("Distance to ref", "dist", lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "&mdash;")

    parts.append('<tr class="header-row"><td class="sticky-l">&mdash; Terpenes &mdash;</td>'
                 f'<td class="sticky-r"></td>{"<td></td>"*(len(cols)-1)}</tr>')

    for k, lbl in zip(_TERP_KEYS, _TERP_LABELS):
        ref_val = cols[0].get(k)
        row = ['<tr>',
               f'<td class="sticky-l">{html_lib.escape(lbl)}</td>',
               f'<td class="sticky-r">{(f"{ref_val:.2f}" if ref_val else "&mdash;")}</td>']
        for i, c in enumerate(cols[1:], start=1):
            cv = c.get(k)
            state = _classify_cell(ref_val, cv)
            style = _CELL_STYLE[state]
            cls = ' class="exact"' if i in exact_idx else ''
            txt = f"{cv:.2f}" if cv is not None else "&mdash;"
            row.append(f'<td{cls} style="{style}">{txt}</td>')
        row.append('</tr>')
        parts.append("".join(row))

    parts.append('</tbody></table></div>')
    parts.append('<div class="legend">'
                 '<span class="clone">green column = profile clone (every measured terp within 0.05 of ref)</span>'
                 '<span class="high">red - way more than ref</span>'
                 '<span class="low">amber - way less than ref</span>'
                 '<span class="miss">gray - lab did not report it</span>'
                 '</div>')
    parts.append(f'<div class="sub" style="margin-top:14px;">Generated {datetime.now().strftime("%a %b %d %Y, %I:%M %p")} from {html_lib.escape(dispensary_name)} live menu snapshot.</div>')
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

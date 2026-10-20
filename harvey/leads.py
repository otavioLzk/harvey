"""Local-business lead list — phone-first, for outreach by WhatsApp or a visit.

`harvey export` is built around deliverable email addresses. Small local
businesses in Brazil mostly have none, so this list keys on the company and
its phone instead: one row per business, with the number normalised, whether
it is a mobile (i.e. WhatsApp-reachable), a wa.me link, and the confirmed
signals that give a concrete reason to call.
"""

import csv
import io

import aiosqlite

from harvey.br import parse_br_phone
from harvey.state import StateManager

CSV_COLUMNS = [
    "company_name", "industry", "phone", "phone_e164", "phone_type",
    "whatsapp_link", "has_website", "website", "address", "rating",
    "review_count", "signals", "maps_url", "source",
]

# Signals worth naming to a business owner, in the order a salesperson would
# lead with them.
PITCH_ORDER = ("NO_WEBSITE", "UNCLAIMED_LISTING", "NO_ONLINE_BOOKING",
               "NO_SCHEMA_MARKUP", "BLOG_STALE", "RUNNING_GOOGLE_ADS",
               "RUNNING_META_ADS", "INCUMBENT_AGENCY")


async def collect_leads(state: StateManager, whatsapp_only: bool = False,
                        no_website_only: bool = False) -> list[dict]:
    async with aiosqlite.connect(state.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM companies ORDER BY created_at DESC"
        ) as cur:
            companies = [dict(r) for r in await cur.fetchall()]
        async with db.execute(
            """SELECT company_id, signal_code, value_num, value_text
               FROM observations WHERE company_id != ''
               ORDER BY observed_at"""
        ) as cur:
            obs = [dict(r) for r in await cur.fetchall()]

    by_company: dict[str, dict[str, dict]] = {}
    for o in obs:
        # Later observations overwrite earlier ones: the latest value wins.
        by_company.setdefault(o["company_id"], {})[o["signal_code"]] = o

    out = []
    for c in companies:
        signals = by_company.get(c["id"], {})
        phone = parse_br_phone(c.get("phone") or "")
        has_site = bool(c.get("website") or c.get("domain"))
        if whatsapp_only and not phone.whatsapp:
            continue
        if no_website_only and has_site:
            continue
        rating = signals.get("REVIEW_RATING", {}).get("value_num")
        reviews = signals.get("REVIEW_COUNT", {}).get("value_num")
        pitch = [code for code in PITCH_ORDER if code in signals]
        if not has_site and "NO_WEBSITE" not in pitch:
            pitch.insert(0, "NO_WEBSITE")
        out.append({
            "company_name": c.get("name", ""),
            "industry": c.get("industry", ""),
            "phone": c.get("phone", ""),
            "phone_e164": phone.e164,
            "phone_type": phone.kind,
            "whatsapp_link": phone.wa_link,
            "has_website": "sim" if has_site else "nao",
            "website": c.get("website", ""),
            "address": c.get("location", ""),
            "rating": rating if rating is not None else "",
            "review_count": int(reviews) if reviews is not None else "",
            "signals": ";".join(pitch),
            "maps_url": c.get("source_url", ""),
            "source": c.get("source", ""),
        })
    # Best leads first: no website, then WhatsApp-reachable, then most reviewed.
    out.sort(key=lambda r: (r["has_website"] == "sim", not r["whatsapp_link"],
                            -(r["review_count"] or 0)))
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


async def export_leads_csv(state: StateManager, out_path: str,
                           whatsapp_only: bool = False,
                           no_website_only: bool = False) -> int:
    rows = await collect_leads(state, whatsapp_only, no_website_only)
    # utf-8-sig so Excel on Windows shows accents correctly.
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        f.write(to_csv(rows))
    return len(rows)

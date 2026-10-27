"""Local-business lead list — phone-first, for outreach by WhatsApp or a visit.

`harvey export` is built around deliverable email addresses. Small local
businesses in Brazil mostly have none, so this list keys on the company and
its phone instead: one row per business, with the number normalised, whether
it is a mobile (i.e. WhatsApp-reachable), a wa.me link, and the confirmed
signals that give a concrete reason to call.
"""

import csv
import io
import json
from html import escape
from pathlib import Path

import aiosqlite

from harvey.br import parse_br_phone
from harvey.br_messages import compose_message, wa_link
from harvey.state import StateManager

CSV_COLUMNS = [
    "company_name", "industry", "phone", "phone_e164", "phone_type",
    "score", "whatsapp_link", "whatsapp_message", "has_website", "website", "address", "rating",
    "review_count", "signals", "maps_url", "source", "status", "status_at",
]

# Signals worth naming to a business owner, in the order a salesperson would
# lead with them.
PITCH_ORDER = ("NO_WEBSITE", "WHATSAPP_ONLY_BOOKING", "UNCLAIMED_LISTING",
               "NO_ONLINE_BOOKING", "NO_SCHEMA_MARKUP", "BLOG_STALE",
               "RUNNING_GOOGLE_ADS", "RUNNING_META_ADS", "INCUMBENT_AGENCY")

STALE_DAYS = 180

# Where each lead stands, as the person works the list.
STATUSES = {
    "novo": "Não contatado",
    "enviado": "Mensagem enviada",
    "negociando": "Em negociação",
    "fechado": "Venda fechada",
    "sem_interesse": "Sem interesse",
}
# settings key per lead: "<status>|<ISO date>".
STATUS_PREFIX = "lead_status:"
# settings keys holding the name and business that sign each message.
SENDER_NAME_KEY = "lead_sender_name"
SENDER_COMPANY_KEY = "lead_sender_company"

# Points toward "worth a message today". Gaps we can sell into, plus proof the
# business already has demand (reviews) and can be reached (a mobile number).
SCORE_POINTS = {"NO_WEBSITE": 40, "WHATSAPP_ONLY_BOOKING": 30,
                "NO_ONLINE_BOOKING": 20, "UNCLAIMED_LISTING": 15,
                "BLOG_STALE": 10, "NO_SCHEMA_MARKUP": 5,
                "RUNNING_GOOGLE_ADS": 5, "RUNNING_META_ADS": 5,
                "INCUMBENT_AGENCY": -15}


def _holds(code: str, o: dict) -> bool:
    """Whether an observation says the signal is TRUE for this business.

    Profile signals are recorded both ways (NO_ONLINE_BOOKING = 0 when a
    booking tool was found), so presence alone is not enough.
    """
    num = o.get("value_num")
    if code == "BLOG_STALE":
        return num is not None and num >= STALE_DAYS
    if num is None:
        return bool(o.get("value_text"))
    return num != 0


def score_lead(pitch: list[str], rating, reviews, has_mobile: bool) -> int:
    pts = sum(SCORE_POINTS.get(code, 0) for code in pitch)
    if "WHATSAPP_ONLY_BOOKING" in pitch and "NO_ONLINE_BOOKING" in pitch:
        pts -= SCORE_POINTS["NO_ONLINE_BOOKING"]     # same gap, count it once
    reviews = reviews or 0
    pts += 20 if reviews >= 50 else 12 if reviews >= 20 else 5 if reviews >= 5 else 0
    if rating:
        pts += 10 if rating >= 4.5 else 5 if rating >= 4.0 else 0
    if has_mobile:
        pts += 10
    return max(0, min(100, pts))


async def collect_leads(state: StateManager, whatsapp_only: bool = False,
                        no_website_only: bool = False, sender: str = "",
                        company: str = "") -> list[dict]:
    """One row per business. ``sender``/``company`` sign the drafted message."""
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
        async with db.execute(
            "SELECT key, value FROM settings WHERE key LIKE ?",
            (STATUS_PREFIX + "%",),
        ) as cur:
            statuses = {r["key"][len(STATUS_PREFIX):]: (r["value"] + "|").split("|")[:2]
                        for r in await cur.fetchall() if r["value"]}

    by_company: dict[str, dict[str, dict]] = {}
    for o in obs:
        # Later observations overwrite earlier ones: the latest value wins.
        by_company.setdefault(o["company_id"], {})[o["signal_code"]] = o

    out, phones = [], []
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
        pitch = [code for code in PITCH_ORDER
                 if code in signals and _holds(code, signals[code])]
        if not has_site and "NO_WEBSITE" not in pitch:
            pitch.insert(0, "NO_WEBSITE")
        phones.append(phone)
        out.append({
            "id": c["id"],
            "status": statuses.get(c["id"], ["novo", ""])[0],
            "status_at": statuses.get(c["id"], ["novo", ""])[1],
            "company_name": c.get("name", ""),
            "industry": c.get("industry", ""),
            "phone": c.get("phone", ""),
            "phone_e164": phone.e164,
            "phone_type": phone.kind,
            "score": score_lead(pitch, rating, reviews, phone.whatsapp),
            "whatsapp_link": "",
            "whatsapp_message": "",
            "has_website": "sim" if has_site else "nao",
            "website": c.get("website", ""),
            "address": c.get("location", ""),
            "rating": rating if rating is not None else "",
            "review_count": int(reviews) if reviews is not None else "",
            "signals": ";".join(pitch),
            "maps_url": c.get("source_url", ""),
            "source": c.get("source", ""),
        })
    for row, phone in zip(out, phones):
        row["whatsapp_message"] = compose_message(row, sender, company)
        if phone.whatsapp:
            row["whatsapp_link"] = wa_link(phone.e164, row["whatsapp_message"])
    # Best leads first; ties go to the business with more reviews.
    out.sort(key=lambda r: (-r["score"], -(r["review_count"] or 0)))
    return out


def niche_report(rows: list[dict]) -> list[dict]:
    """Per niche: how many businesses, and how many carry each sellable gap.

    Answers "where do I start?" with counts from this city instead of a guess.
    """
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault((r["industry"] or "sem categoria").strip().lower(), []).append(r)
    report = []
    for niche, items in by.items():
        has = lambda code: sum(1 for r in items if code in r["signals"].split(";"))
        report.append({
            "niche": niche,
            "total": len(items),
            "mobile": sum(1 for r in items if r["phone_type"] == "mobile"),
            "no_website": has("NO_WEBSITE"),
            "no_booking": sum(1 for r in items if {"NO_ONLINE_BOOKING", "WHATSAPP_ONLY_BOOKING"}
                              & set(r["signals"].split(";"))),
            "well_reviewed": sum(1 for r in items if (r["review_count"] or 0) >= 20
                                 and (r["rating"] or 0) >= 4.5),
            "avg_score": round(sum(r["score"] for r in items) / len(items)),
        })
    report.sort(key=lambda n: (-n["avg_score"] * n["total"], n["niche"]))
    return report


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def to_html(rows: list[dict], title: str = "Leads") -> str:
    """A standalone page to work the list from, grouped by niche.

    Statuses picked on the page are kept in that browser (localStorage); the
    dashboard's Leads tab keeps them in the database instead. Both render with
    the same board (harvey/web/leads-board.*).
    """
    data = json.dumps(rows, ensure_ascii=False, default=str).replace("</", "<\\/")
    return (HTML_PAGE
            .replace("{title}", escape(title))
            .replace("{count}", str(len(rows)))
            .replace("{board_css}", (WEB_DIR / "leads-board.css").read_text(encoding="utf-8"))
            .replace("{board_js}", (WEB_DIR / "leads-board.js").read_text(encoding="utf-8"))
            .replace("{data}", data))


WEB_DIR = Path(__file__).resolve().parent / "web"

HTML_PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {
  --bg:#FBFAF8; --panel:#FFFFFF; --panel-raised:#F5F3EF; --border:#E8E4DD; --border-strong:#D3CDC3;
  --text:#1E1B17; --text-2:#5E584F; --text-3:#948D82; --r-md:6px;
  --s-good:#2F7A45; --s-good-bg:#E6F1E9; --s-wait:#8A6A1F; --s-wait-bg:#FAF2DC;
  --s-bad:#96322E; --s-bad-bg:#FBEBE9; --s-active:#2C5F7C; --s-active-bg:#E9F0F5;
  --s-note:#5B4A72; --s-note-bg:#F1EDF6;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#131210; --panel:#1A1917; --panel-raised:#221F1C; --border:#2B2825; --border-strong:#3D3934;
    --text:#ECE8E1; --text-2:#B5AEA3; --text-3:#857E73;
    --s-good:#7FC492; --s-good-bg:#1B2A20; --s-wait:#D9B45E; --s-wait-bg:#2B2416;
    --s-bad:#E58A84; --s-bad-bg:#2E1A18; --s-active:#86B6D4; --s-active-bg:#172430;
    --s-note:#B7A6D0; --s-note-bg:#231E2C;
    color-scheme: dark;
  }
}
body { margin:0; padding:16px; background:var(--bg); color:var(--text);
       font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:860px; margin:0 auto; }
h1 { font-size:22px; margin:4px 0 4px; }
.lede { color:var(--text-2); font-size:13px; margin:0 0 16px; }
{board_css}
</style></head>
<body><main>
<h1>{title} ({count})</h1>
<p class="lede">Toque num tipo de negócio para ver as empresas, e numa empresa para ver a mensagem.
Mude o status de cada uma conforme a conversa anda. O status fica salvo neste navegador.</p>
<div id="board"></div>
</main>
<script>
{board_js}
</script>
<script>
(function () {
  var leads = {data};
  var KEY = "leadstatus:";
  leads.forEach(function (l) {
    try {
      var saved = JSON.parse(localStorage.getItem(KEY + l.id) || "null");
      if (saved) { l.status = saved.status; l.status_at = saved.at; }
    } catch (e) { /* storage blocked: start from the exported status */ }
  });
  LeadBoard.mount(document.getElementById("board"), {
    leads: leads,
    save: function (id, status) {
      try {
        localStorage.setItem(KEY + id, JSON.stringify({status: status, at: new Date().toISOString().slice(0, 10)}));
        return Promise.resolve(true);
      } catch (e) { return Promise.resolve(false); }
    },
    onError: function (msg) { alert(msg + " Este navegador não deixa salvar; use a planilha."); }
  });
})();
</script>
</body></html>
"""


async def export_leads_csv(state: StateManager, out_path: str,
                           whatsapp_only: bool = False,
                           no_website_only: bool = False,
                           sender: str = "", company: str = "",
                           html_path: str = "") -> list[dict]:
    rows = await collect_leads(state, whatsapp_only, no_website_only,
                               sender, company)
    # utf-8-sig so Excel on Windows shows accents correctly.
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        f.write(to_csv(rows))
    if html_path:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(to_html(rows))
    return rows

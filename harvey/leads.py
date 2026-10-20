"""Local-business lead list — phone-first, for outreach by WhatsApp or a visit.

`harvey export` is built around deliverable email addresses. Small local
businesses in Brazil mostly have none, so this list keys on the company and
its phone instead: one row per business, with the number normalised, whether
it is a mobile (i.e. WhatsApp-reachable), a wa.me link, and the confirmed
signals that give a concrete reason to call.
"""

import csv
import io
from html import escape

import aiosqlite

from harvey.br import parse_br_phone
from harvey.br_messages import compose_message, wa_link
from harvey.state import StateManager

CSV_COLUMNS = [
    "company_name", "industry", "phone", "phone_e164", "phone_type",
    "whatsapp_link", "whatsapp_message", "has_website", "website", "address", "rating",
    "review_count", "signals", "maps_url", "source",
]

# Signals worth naming to a business owner, in the order a salesperson would
# lead with them.
PITCH_ORDER = ("NO_WEBSITE", "UNCLAIMED_LISTING", "NO_ONLINE_BOOKING",
               "NO_SCHEMA_MARKUP", "BLOG_STALE", "RUNNING_GOOGLE_ADS",
               "RUNNING_META_ADS", "INCUMBENT_AGENCY")


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
        pitch = [code for code in PITCH_ORDER if code in signals]
        if not has_site and "NO_WEBSITE" not in pitch:
            pitch.insert(0, "NO_WEBSITE")
        phones.append(phone)
        out.append({
            "company_name": c.get("name", ""),
            "industry": c.get("industry", ""),
            "phone": c.get("phone", ""),
            "phone_e164": phone.e164,
            "phone_type": phone.kind,
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


def to_html(rows: list[dict]) -> str:
    """A page to work the list from: read the draft, tap, send, next."""
    def card(r):
        signals = ", ".join(SIGNAL_LABELS.get(s, s) for s in r["signals"].split(";") if s)
        button = (f'<a class="wa" href="{escape(r["whatsapp_link"])}" target="_blank" '
                  f'rel="noopener">Abrir no WhatsApp</a>' if r["whatsapp_link"]
                  else f'<span class="muted">Telefone fixo: ligue ou visite</span>')
        maps = (f' · <a href="{escape(r["maps_url"])}" target="_blank" rel="noopener">mapa</a>'
                if r["maps_url"] else "")
        return f"""<article>
  <h2>{escape(r["company_name"])}</h2>
  <p class="muted">{escape(r["industry"])} · {escape(r["phone"] or "sem telefone")}{maps}</p>
  <p class="muted">{escape(r["address"])}</p>
  {f'<p class="tags">{escape(signals)}</p>' if signals else ""}
  <textarea rows="8">{escape(r["whatsapp_message"])}</textarea>
  <p>{button}</p>
</article>"""
    body = "\n".join(card(r) for r in rows) or "<p>Nenhum lead ainda.</p>"
    return HTML_PAGE.replace("{count}", str(len(rows))).replace("{body}", body)


SIGNAL_LABELS = {
    "NO_WEBSITE": "sem site", "UNCLAIMED_LISTING": "perfil do Google não reivindicado",
    "NO_ONLINE_BOOKING": "sem agendamento online", "NO_SCHEMA_MARKUP": "SEO básico faltando",
    "BLOG_STALE": "site desatualizado", "RUNNING_GOOGLE_ADS": "anuncia no Google",
    "RUNNING_META_ADS": "anuncia no Instagram/Facebook", "INCUMBENT_AGENCY": "já tem agência",
}

HTML_PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Leads</title>
<style>
:root { --bg:#f7f7f5; --card:#fff; --text:#1d1d1b; --muted:#6b6b66; --line:#e3e3de; --wa:#1f8f4e; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --card:#21211f; --text:#ededea; --muted:#a3a39d; --line:#34342f; --wa:#2fb067; }
}
body { margin:0; padding:16px; background:var(--bg); color:var(--text);
       font:15px/1.45 system-ui, sans-serif; }
main { max-width:720px; margin:0 auto; }
article { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:14px 16px; margin:12px 0; }
h1 { font-size:20px; } h2 { font-size:17px; margin:0 0 4px; }
p { margin:4px 0; } .muted { color:var(--muted); font-size:13px; }
.tags { font-size:13px; }
textarea { width:100%; box-sizing:border-box; margin:8px 0; padding:8px; font:inherit;
           background:var(--bg); color:var(--text); border:1px solid var(--line);
           border-radius:6px; resize:vertical; }
a { color:inherit; }
.wa { display:inline-block; background:var(--wa); color:#fff; text-decoration:none;
      padding:8px 14px; border-radius:6px; font-weight:600; }
</style></head>
<body><main>
<h1>Leads ({count})</h1>
<p class="muted">Sem site primeiro, depois quem tem celular. Você pode editar o texto: o botão envia o que estiver na caixa.</p>
{body}
</main>
<script>
// The button sends whatever is in the box, so edits are not lost.
document.querySelectorAll("a.wa").forEach(function (a) {
  a.addEventListener("click", function () {
    var box = a.closest("article").querySelector("textarea");
    a.href = a.href.split("?")[0] + "?text=" + encodeURIComponent(box.value);
  });
});
</script>
</body></html>
"""


async def export_leads_csv(state: StateManager, out_path: str,
                           whatsapp_only: bool = False,
                           no_website_only: bool = False,
                           sender: str = "", company: str = "",
                           html_path: str = "") -> int:
    rows = await collect_leads(state, whatsapp_only, no_website_only,
                               sender, company)
    # utf-8-sig so Excel on Windows shows accents correctly.
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        f.write(to_csv(rows))
    if html_path:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(to_html(rows))
    return len(rows)

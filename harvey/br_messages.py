"""First-contact WhatsApp message per lead, in Brazilian Portuguese.

Deterministic on purpose: no model call, so a list of 500 leads costs
nothing and the same lead always gets the same text. The message names one
concrete thing about the business (the strongest signal it carries), offers
something small, and asks one easy question. It does not pitch a price.

The person sends it themselves; this only writes the draft. Wording avoids
gendered articles ("a/o {name}") because business names don't tell us which
one fits.
"""

import zlib
from urllib.parse import quote

GREETINGS = ("Oi, {name}! Tudo bem?", "Olá, {name}! Tudo bem?",
             "Oi, {name}, tudo certo?")

# Strongest reason first. Each line is about the business, not about us.
OBSERVATIONS = {
    "NO_WEBSITE": "Vi o perfil de vocês no Google Maps e reparei que ainda não "
                  "têm um site.",
    "UNCLAIMED_LISTING": "Vi o perfil de vocês no Google Maps e reparei que ele "
                         "ainda não foi reivindicado no Google.",
    "NO_ONLINE_BOOKING": "Dei uma olhada no site de vocês e vi que ainda não dá "
                         "para agendar direto por lá.",
    "BLOG_STALE": "Dei uma olhada no site de vocês e vi que ele está sem "
                  "atualização faz um tempo.",
    "NO_SCHEMA_MARKUP": "Dei uma olhada no site de vocês e vi alguns ajustes "
                        "simples que fariam vocês aparecerem melhor no Google.",
}
OBSERVATION_ORDER = tuple(OBSERVATIONS)
GENERIC = "Vi o perfil de vocês no Google Maps."

OFFERS = {
    "NO_WEBSITE": "Eu faço sites para negócios aqui da região, e um site simples "
                  "costuma trazer clientes que hoje procuram no Google e não "
                  "acham vocês.",
    "UNCLAIMED_LISTING": "Eu ajudo negócios daqui a cuidar disso e a montar um "
                         "site, para aparecerem melhor quando alguém procura.",
    "NO_ONLINE_BOOKING": "Eu monto sites com agendamento online, assim o cliente "
                         "marca sozinho, até fora do horário.",
    "BLOG_STALE": "Eu cuido de sites para negócios aqui da região e posso "
                  "deixar o de vocês em dia sem dar trabalho.",
    "NO_SCHEMA_MARKUP": "Eu cuido de sites para negócios aqui da região.",
}
GENERIC_OFFER = "Eu faço sites e cuido da presença online de negócios aqui da região."

CLOSES = ("Posso te mandar uma ideia de como ficaria, sem compromisso?",
          "Se fizer sentido, posso te mostrar um exemplo rápido. Pode ser?",
          "Quer que eu te mande um exemplo de como ficaria?")


def _pick(options: tuple[str, ...], key: str) -> str:
    # Stable per business, varied across the list.
    return options[zlib.crc32(key.encode()) % len(options)]


def _praise(rating, reviews) -> str:
    try:
        rating, reviews = float(rating), int(reviews)
    except (TypeError, ValueError):
        return ""
    if rating >= 4.5 and reviews >= 20:
        nota = f"{rating:.1f}".replace(".", ",")
        return f"Nota {nota} com {reviews} avaliações, parabéns pelo trabalho!"
    return ""


def compose_message(lead: dict, sender: str = "", company: str = "") -> str:
    """The draft for one lead row from `harvey.leads.collect_leads`."""
    name = (lead.get("company_name") or "").strip() or "pessoal"
    signals = [s for s in (lead.get("signals") or "").split(";") if s]
    main = next((s for s in OBSERVATION_ORDER if s in signals), "")

    intro = ""
    if sender:
        intro = f"Meu nome é {sender}" + (f", da {company}" if company else "") + "."
    parts = [
        _pick(GREETINGS, name).format(name=name),
        intro,
        OBSERVATIONS.get(main, GENERIC),
        _praise(lead.get("rating"), lead.get("review_count")),
        OFFERS.get(main, GENERIC_OFFER),
        _pick(CLOSES, name),
    ]
    return " ".join(p for p in parts if p)


def wa_link(e164: str, message: str = "") -> str:
    """wa.me link that opens the chat with the message already typed."""
    if not e164:
        return ""
    base = f"https://wa.me/{e164.lstrip('+')}"
    return f"{base}?text={quote(message)}" if message else base

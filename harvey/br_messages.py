"""First-contact WhatsApp message per lead, in Brazilian Portuguese.

Deterministic on purpose: no model call, so a list of 500 leads costs
nothing and the same lead always gets the same text. The message greets by
time of day, says who is writing and what they do, names one concrete thing
about the business (the strongest signal it carries) and why it matters, and
offers a preview. It does not pitch a price.

The person sends it themselves; this only writes the draft. Wording avoids
gendered articles ("a/o {name}") because business names don't tell us which
one fits. The greeting is refreshed by the lead board to the clock of the
computer it's opened on, so a list written in the morning still reads right
at night.
"""

import re
import zlib
from datetime import datetime
from urllib.parse import quote

GREETINGS = ("{greet}, {name}! Tudo bem?", "{greet}, {name}! Tudo certo por aí?")

INTRO = ("e trabalho criando sites para empresas aqui da região, pensados para o "
         "negócio ser encontrado com mais facilidade e se apresentar bem para os "
         "clientes.")

# Strongest reason first: what we noticed, then why it matters to them.
OBSERVATIONS = {
    "NO_WEBSITE": "Dei uma olhada no perfil de vocês no Google e percebi que ainda "
                  "não têm um site. Hoje muita gente pesquisa no Google antes de "
                  "escolher onde ir, e um site simples ajuda esses clientes a "
                  "encontrarem vocês e a conhecerem melhor o trabalho de vocês.",
    "WHATSAPP_ONLY_BOOKING": "Dei uma olhada no site de vocês e vi que os horários "
                             "são marcados pelo WhatsApp. Com um agendamento online, "
                             "o próprio cliente escolhe o horário e recebe um lembrete "
                             "automático, e vocês ganham tempo no dia a dia.",
    "UNCLAIMED_LISTING": "Dei uma olhada no perfil de vocês no Google e vi que ele "
                         "ainda não foi reivindicado. Com o perfil em dia e um site, "
                         "fica bem mais fácil para quem procura encontrar e confiar "
                         "no trabalho de vocês.",
    "NO_ONLINE_BOOKING": "Dei uma olhada no site de vocês e vi que ainda não dá "
                         "para agendar direto por lá. Com o agendamento online, o "
                         "cliente marca sozinho, até fora do horário de atendimento.",
    "BLOG_STALE": "Dei uma olhada no site de vocês e vi que ele está sem "
                  "atualização faz um tempo. Um site atualizado passa mais "
                  "confiança para quem chega por lá e ajuda vocês a aparecerem "
                  "melhor no Google.",
    "NO_SCHEMA_MARKUP": "Dei uma olhada no site de vocês e vi alguns ajustes "
                        "simples que ajudariam vocês a aparecerem melhor nas "
                        "buscas do Google.",
}
OBSERVATION_ORDER = tuple(OBSERVATIONS)
GENERIC = ("Dei uma olhada no perfil de vocês no Google e acredito que um site "
           "bem feito pode ajudar mais clientes a encontrarem e conhecerem o "
           "trabalho de vocês.")

# What the preview would show, per signal.
PREVIEWS = {
    "WHATSAPP_ONLY_BOOKING": "o agendamento online de vocês",
    "NO_ONLINE_BOOKING": "o agendamento online no site de vocês",
    "BLOG_STALE": "o site de vocês renovado",
    "NO_SCHEMA_MARKUP": "o site de vocês com esses ajustes",
}
PREVIEW = "o site de vocês"

CLOSES = ("Se quiser, posso montar uma prévia de como ficaria {what}, sem "
          "compromisso. Teria interesse em dar uma olhada?",
          "Posso preparar uma prévia de como ficaria {what}, sem compromisso "
          "nenhum. Teria interesse em ver?")


def greeting(now: datetime | None = None) -> str:
    """Bom dia / Boa tarde / Boa noite for the given (default: local) time."""
    hour = (now or datetime.now()).hour
    if 5 <= hour < 12:
        return "Bom dia"
    if 12 <= hour < 18:
        return "Boa tarde"
    return "Boa noite"


# Google names are often stuffed for search: "Dra Ana | Botox | Preenchimento",
# "Salão X em São Sebastião do Paraíso MG". Greet by the part a person would say.
_NAME_SPLIT = re.compile(r"\s*\|\s*|\s+[-–—]\s+|:\s+")
_CITY_TAIL = re.compile(r"\s+(?:em\s+)?S[ãa]o\s+Sebast\w*(?:\s+do\s+Para\w*)?"
                        r"(?:\s*-?\s*MG)?\s*$", re.I)


def short_name(name: str) -> str:
    """The business name as you'd say it in a greeting."""
    name = " ".join(name.split())
    parts = [p.strip() for p in _NAME_SPLIT.split(name) if p.strip()] or [name]
    # "DENTISTA - Dra. Ana": a lone capitalised category, the name comes after.
    first = parts[1] if len(parts) > 1 and " " not in parts[0] and parts[0].isupper() else parts[0]
    trimmed = _CITY_TAIL.sub("", first).strip()
    return trimmed if len(trimmed.split()) >= 2 else first


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
        return (f"Aliás, parabéns pela nota {nota} com {reviews} avaliações, "
                f"dá para ver o capricho de vocês!")
    return ""


def compose_message(lead: dict, sender: str = "", company: str = "",
                    now: datetime | None = None) -> str:
    """The draft for one lead row from `harvey.leads.collect_leads`."""
    name = (lead.get("company_name") or "").strip() or "pessoal"
    signals = [s for s in (lead.get("signals") or "").split(";") if s]
    main = next((s for s in OBSERVATION_ORDER if s in signals), "")

    if sender:
        intro = f"Me chamo {sender}" + (f", da {company}," if company else "") + " " + INTRO
    else:
        intro = "Trabalho criando sites" + INTRO.split("criando sites", 1)[1]
    body = " ".join(p for p in (OBSERVATIONS.get(main, GENERIC),
                                _praise(lead.get("rating"), lead.get("review_count"))) if p)
    paragraphs = [
        _pick(GREETINGS, name).format(greet=greeting(now), name=short_name(name)),
        intro,
        body,
        _pick(CLOSES, name).format(what=PREVIEWS.get(main, PREVIEW)),
    ]
    return "\n\n".join(paragraphs)


def wa_link(e164: str, message: str = "") -> str:
    """wa.me link that opens the chat with the message already typed."""
    if not e164:
        return ""
    base = f"https://wa.me/{e164.lstrip('+')}"
    return f"{base}?text={quote(message)}" if message else base

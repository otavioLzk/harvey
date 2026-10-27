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

# Three ways of saying the same thing, so a whole list doesn't go out word
# for word. Each business always gets the same one (picked from its name);
# across the list they come out mixed. Every style has the same parts: a
# greeting, who is writing, what we noticed and why it matters, a compliment
# when the reviews earn one, and an offer of a preview.
STYLES = (
    {
        "greeting": "{greet}, {name}! Tudo certo por aí?",
        "intro": "Me chamo {sender}{company} e trabalho criando sites para empresas "
                 "aqui da região, pensados para o negócio ser encontrado com mais "
                 "facilidade e se apresentar bem para os clientes.",
        "intro_anon": "Trabalho criando sites para empresas aqui da região, pensados "
                      "para o negócio ser encontrado com mais facilidade e se "
                      "apresentar bem para os clientes.",
        "observations": {
            "NO_WEBSITE": "Dei uma olhada no perfil de vocês no Google e percebi que "
                          "ainda não têm um site. Hoje muita gente pesquisa no Google "
                          "antes de escolher onde ir, e um site simples ajuda esses "
                          "clientes a encontrarem vocês e a conhecerem melhor o "
                          "trabalho de vocês.",
            "WHATSAPP_ONLY_BOOKING": "Dei uma olhada no site de vocês e vi que os "
                                     "horários são marcados pelo WhatsApp. Com um "
                                     "agendamento online, o próprio cliente escolhe o "
                                     "horário e recebe um lembrete automático, e vocês "
                                     "ganham tempo no dia a dia.",
            "UNCLAIMED_LISTING": "Dei uma olhada no perfil de vocês no Google e vi que "
                                 "ele ainda não foi reivindicado. Com o perfil em dia e "
                                 "um site, fica bem mais fácil para quem procura "
                                 "encontrar e confiar no trabalho de vocês.",
            "NO_ONLINE_BOOKING": "Dei uma olhada no site de vocês e vi que ainda não dá "
                                 "para agendar direto por lá. Com o agendamento online, "
                                 "o cliente marca sozinho, até fora do horário de "
                                 "atendimento.",
            "BLOG_STALE": "Dei uma olhada no site de vocês e vi que ele está sem "
                          "atualização faz um tempo. Um site atualizado passa mais "
                          "confiança para quem chega por lá e ajuda vocês a "
                          "aparecerem melhor no Google.",
            "NO_SCHEMA_MARKUP": "Dei uma olhada no site de vocês e vi alguns ajustes "
                                "simples que ajudariam vocês a aparecerem melhor nas "
                                "buscas do Google.",
        },
        "generic": "Dei uma olhada no perfil de vocês no Google e acredito que um site "
                   "bem feito pode ajudar mais clientes a encontrarem e conhecerem o "
                   "trabalho de vocês.",
        "praise": "Aliás, parabéns pela nota {nota} com {reviews} avaliações, dá para "
                  "ver o capricho de vocês!",
        "close": "Posso preparar uma prévia de como ficaria {what}, sem compromisso "
                 "nenhum. Teria interesse em ver?",
    },
    {
        "greeting": "{greet}, {name}! Tudo bem com vocês?",
        "intro": "Aqui quem fala é {sender}{company}. Eu desenvolvo sites para negócios "
                 "aqui da região, com foco em deixar a empresa bem apresentada e fácil "
                 "de achar na internet.",
        "intro_anon": "Eu desenvolvo sites para negócios aqui da região, com foco em "
                      "deixar a empresa bem apresentada e fácil de achar na internet.",
        "observations": {
            "NO_WEBSITE": "Encontrei vocês pelo Google e notei que a empresa ainda não "
                          "tem um site. Quando alguém procura pelo serviço e encontra "
                          "um site bem feito, a chance de entrar em contato é bem "
                          "maior, e isso faz diferença no movimento.",
            "WHATSAPP_ONLY_BOOKING": "Entrei no site de vocês e notei que o agendamento "
                                     "é feito todo pelo WhatsApp. Dá para deixar o "
                                     "cliente marcar sozinho pelo site, com lembrete "
                                     "automático, e liberar o tempo que hoje vai em "
                                     "responder mensagem.",
            "UNCLAIMED_LISTING": "Encontrei vocês pelo Google e notei que o perfil da "
                                 "empresa ainda não foi reivindicado. Ajustando isso e "
                                 "tendo um site, vocês passam mais confiança para quem "
                                 "está pesquisando.",
            "NO_ONLINE_BOOKING": "Entrei no site de vocês e notei que ainda não tem "
                                 "como agendar por ele. Com agendamento online, o "
                                 "cliente marca na hora em que lembrar, mesmo com a "
                                 "empresa fechada.",
            "BLOG_STALE": "Entrei no site de vocês e notei que ele não é atualizado "
                          "faz um tempo. Uma renovada passa uma imagem mais atual e "
                          "ajuda a empresa a aparecer melhor nas buscas.",
            "NO_SCHEMA_MARKUP": "Entrei no site de vocês e notei alguns detalhes "
                                "técnicos que, ajustados, ajudam vocês a aparecerem "
                                "melhor no Google.",
        },
        "generic": "Encontrei vocês pelo Google e acho que um site bem feito pode "
                   "trazer mais clientes e valorizar ainda mais o trabalho de vocês.",
        "praise": "E que avaliação, hein? Nota {nota} com {reviews} avaliações, "
                  "parabéns!",
        "close": "Se fizer sentido para vocês, posso montar uma prévia de como ficaria "
                 "{what}, sem compromisso. Posso te mandar?",
    },
    {
        "greeting": "{greet}, {name}, tudo bem?",
        "intro": "Meu nome é {sender}{company} e eu ajudo empresas aqui da região a "
                 "terem um site profissional, que apareça no Google e mostre bem o "
                 "trabalho delas.",
        "intro_anon": "Eu ajudo empresas aqui da região a terem um site profissional, "
                      "que apareça no Google e mostre bem o trabalho delas.",
        "observations": {
            "NO_WEBSITE": "Pesquisando no Google, vi o perfil de vocês e reparei que "
                          "ainda não há um site. Muita gente decide onde ir pelo que "
                          "encontra na internet, então ter um site próprio ajuda a não "
                          "perder esses clientes para a concorrência.",
            "WHATSAPP_ONLY_BOOKING": "Pesquisando no Google, cheguei ao site de vocês e "
                                     "reparei que os horários são marcados pelo "
                                     "WhatsApp. Um agendamento online organiza a agenda "
                                     "sozinho, manda lembrete para o cliente e ajuda a "
                                     "diminuir as faltas.",
            "UNCLAIMED_LISTING": "Pesquisando no Google, vi o perfil de vocês e reparei "
                                 "que ele ainda não foi reivindicado. Com o perfil "
                                 "verificado e um site, a empresa fica mais fácil de "
                                 "encontrar e passa mais credibilidade.",
            "NO_ONLINE_BOOKING": "Pesquisando no Google, cheguei ao site de vocês e "
                                 "reparei que ainda não é possível agendar por lá. Com "
                                 "o agendamento online, o cliente reserva o horário sem "
                                 "precisar esperar resposta.",
            "BLOG_STALE": "Pesquisando no Google, cheguei ao site de vocês e reparei "
                          "que ele está sem atualizações há um tempo. Um site renovado "
                          "transmite mais confiança e ajuda a aparecer nas buscas.",
            "NO_SCHEMA_MARKUP": "Pesquisando no Google, cheguei ao site de vocês e "
                                "reparei em alguns ajustes simples que ajudariam a "
                                "empresa a aparecer melhor nos resultados.",
        },
        "generic": "Pesquisando no Google, vi o perfil de vocês e acredito que um site "
                   "próprio pode ajudar a atrair mais clientes e mostrar melhor o "
                   "trabalho de vocês.",
        "praise": "Também vi a nota {nota} com {reviews} avaliações. Parabéns, isso "
                  "mostra o cuidado de vocês com os clientes!",
        "close": "Gostaria de te mostrar uma prévia de como ficaria {what}, sem "
                 "compromisso. Posso te enviar?",
    },
)
# Strongest reason first.
OBSERVATION_ORDER = tuple(STYLES[0]["observations"])

# What the preview would show, per signal.
PREVIEWS = {
    "WHATSAPP_ONLY_BOOKING": "o agendamento online de vocês",
    "NO_ONLINE_BOOKING": "o agendamento online no site de vocês",
    "BLOG_STALE": "o site de vocês renovado",
    "NO_SCHEMA_MARKUP": "o site de vocês com esses ajustes",
}
PREVIEW = "o site de vocês"


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


def style_index(name: str) -> int:
    """Which of STYLES a business gets: stable per name, mixed across the list."""
    return zlib.crc32(name.encode()) % len(STYLES)


def _praise(rating, reviews, template: str) -> str:
    try:
        rating, reviews = float(rating), int(reviews)
    except (TypeError, ValueError):
        return ""
    if rating >= 4.5 and reviews >= 20:
        nota = f"{rating:.1f}".replace(".", ",")
        return template.format(nota=nota, reviews=reviews)
    return ""


def compose_message(lead: dict, sender: str = "", company: str = "",
                    now: datetime | None = None, style: int | None = None) -> str:
    """The draft for one lead row from `harvey.leads.collect_leads`."""
    name = (lead.get("company_name") or "").strip() or "pessoal"
    signals = [s for s in (lead.get("signals") or "").split(";") if s]
    main = next((s for s in OBSERVATION_ORDER if s in signals), "")
    st = STYLES[style_index(name) if style is None else style % len(STYLES)]

    if sender:
        intro = st["intro"].format(sender=sender, company=f", da {company}," if company else "")
        intro = intro.replace(",.", ".")
    else:
        intro = st["intro_anon"]
    body = " ".join(p for p in (st["observations"].get(main, st["generic"]),
                                _praise(lead.get("rating"), lead.get("review_count"),
                                        st["praise"])) if p)
    paragraphs = [
        st["greeting"].format(greet=greeting(now), name=short_name(name)),
        intro,
        body,
        st["close"].format(what=PREVIEWS.get(main, PREVIEW)),
    ]
    return "\n\n".join(paragraphs)


def wa_link(e164: str, message: str = "") -> str:
    """wa.me link that opens the chat with the message already typed."""
    if not e164:
        return ""
    base = f"https://wa.me/{e164.lstrip('+')}"
    return f"{base}?text={quote(message)}" if message else base

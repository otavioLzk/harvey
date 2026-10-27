"""Brazil lead list — phone parsing, the Google Places adapter, the CSV."""

import csv
import io
import json
import os
import tempfile

import httpx
import pytest
import pytest_asyncio

from harvey.br import parse_br_phone
from harvey.collectors import discover as D
from harvey.config import load_config
from harvey.leads import collect_leads, to_csv
from harvey.signals import SIGNAL_CATALOG, seed_signal_catalog
from harvey.state import StateManager


@pytest.mark.parametrize("raw,e164,kind", [
    ("(11) 98765-4321", "+5511987654321", "mobile"),
    ("+55 21 99876-5432", "+5521998765432", "mobile"),
    ("011 98765-4321", "+5511987654321", "mobile"),
    ("(31) 3333-4444", "+553133334444", "landline"),
    ("0800 123 4567", "", ""),
    ("", "", ""),
    ("12345", "", ""),
])
def test_parse_br_phone(raw, e164, kind):
    p = parse_br_phone(raw)
    assert (p.e164, p.kind) == (e164, kind)
    assert bool(p.wa_link) == (kind == "mobile")


PLACES = {
    "places": [
        {"id": "A1", "displayName": {"text": "Padaria Pão Bom"},
         "nationalPhoneNumber": "(16) 99123-4567",
         "formattedAddress": "Rua X, 10 - Centro, Ribeirão Preto - SP",
         "rating": 4.7, "userRatingCount": 212,
         "googleMapsUri": "https://maps.google.com/?cid=1"},
        {"id": "B2", "displayName": {"text": "Oficina do Zé"},
         "nationalPhoneNumber": "(16) 3322-1100",
         "websiteUri": "https://www.instagram.com/oficinadoze",
         "rating": 4.2, "userRatingCount": 40},
        {"id": "C3", "displayName": {"text": "Clínica Sorriso"},
         "nationalPhoneNumber": "(16) 99888-7766",
         "websiteUri": "https://clinicasorriso.com.br/"},
        {"id": "D4", "displayName": {"text": "Fechada"},
         "businessStatus": "CLOSED_PERMANENTLY"},
    ],
}


def places_client(pages):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["X-Goog-Api-Key"] == "k"
        assert body["regionCode"] == "BR"
        return httpx.Response(200, json=pages[len(seen) - 1])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


@pytest.mark.asyncio
async def test_google_places_parses_and_treats_social_as_no_site():
    client, seen = places_client([PLACES])
    q = D.DiscoveryQuery(term="padaria", location="Ribeirão Preto, SP")
    out = await D.GooglePlaces().fetch(client, {"google_places_api_key": "k"}, q)
    by_name = {b.name: b for b in out}
    assert set(by_name) == {"Padaria Pão Bom", "Oficina do Zé", "Clínica Sorriso"}
    assert by_name["Padaria Pão Bom"].has_website is False
    assert by_name["Oficina do Zé"].has_website is False
    assert by_name["Oficina do Zé"].domain == ""
    assert by_name["Clínica Sorriso"].domain == "clinicasorriso.com.br"
    assert by_name["Padaria Pão Bom"].external_id == "google_places:A1"
    assert seen[0]["textQuery"] == "padaria Ribeirão Preto, SP"


@pytest.mark.asyncio
async def test_google_places_follows_page_tokens_and_costs_each_page():
    first = {"places": PLACES["places"][:1], "nextPageToken": "t2"}
    second = {"places": PLACES["places"][2:3]}
    client, seen = places_client([first, second])
    provider = D.GooglePlaces()
    out = await provider.fetch(client, {"google_places_api_key": "k"},
                               D.DiscoveryQuery(term="x", limit=100))
    assert len(out) == 2 and len(seen) == 2
    assert seen[1]["pageToken"] == "t2"
    assert provider.last_cost == pytest.approx(2 * provider.COST_PER_REQUEST)


@pytest_asyncio.fixture
async def state():
    with tempfile.TemporaryDirectory() as tmp:
        sm = StateManager(os.path.join(tmp, "test.db"))
        await sm.init_db()
        await seed_signal_catalog(sm)
        for sig in SIGNAL_CATALOG:
            await sm.set_signal_status(sig["code"], "confirmed")
        yield sm


@pytest.mark.asyncio
async def test_discovery_to_lead_csv(state, monkeypatch):
    async def fake_fetch(self, client, env, query):
        return [D.GooglePlaces()._parse(p, query) for p in PLACES["places"][:3]]

    async def no_geocode(state, city, radius_km=40, client=None):
        return ""
    monkeypatch.setattr(D.GooglePlaces, "fetch", fake_fetch)
    monkeypatch.setattr(D, "geocode_city", no_geocode)
    monkeypatch.setattr(D.GooglePlaces, "configured", lambda self, env: True)

    report = await D.run_discovery(
        state, load_config(), "google_places",
        [D.DiscoveryQuery(term="padaria", location="Ribeirão Preto, SP")])
    assert report.new_companies == 3

    rows = await collect_leads(state)
    assert [r["company_name"] for r in rows] == [
        "Padaria Pão Bom", "Oficina do Zé", "Clínica Sorriso"]
    padaria = rows[0]
    assert padaria["whatsapp_link"].startswith("https://wa.me/5516991234567?text=")
    assert "site" in padaria["whatsapp_message"]
    assert rows[1]["whatsapp_link"] == ""          # landline: no WhatsApp
    assert rows[1]["whatsapp_message"]             # still a draft for a call or visit
    assert padaria["signals"].startswith("NO_WEBSITE")
    assert padaria["review_count"] == 212
    assert rows[1]["phone_type"] == "landline"

    only_wa = await collect_leads(state, whatsapp_only=True, no_website_only=True)
    assert [r["company_name"] for r in only_wa] == ["Padaria Pão Bom"]

    parsed = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert parsed[0]["address"].startswith("Rua X")


def test_osm_understands_portuguese_trades_without_accents():
    osm = D.OpenStreetMap()
    assert osm._tags("Padaria") == ["shop=bakery"]
    assert osm._tags("salão de beleza") == ["shop=hairdresser", "shop=beauty"]
    assert osm._tags("barbearia") == ["shop=hairdresser"]
    assert osm._tags("clínica veterinária") == ["amenity=veterinary"]
    assert osm._tags("oficina mecânica") == ["shop=car_repair"]
    assert osm._tags("roofing contractor") == ["craft=roofer", "shop=roofing"]


@pytest.mark.asyncio
async def test_serper_places_parses_and_pages():
    page1 = {"places": [
        {"title": f"Loja {i}", "phoneNumber": "(16) 99123-45%02d" % i,
         "address": "Centro", "cid": str(i),
         "website": "https://instagram.com/x" if i == 0 else ""}
        for i in range(10)]}
    page2 = {"places": [{"title": "Clínica", "phoneNumber": "(16) 3322-1100",
                         "website": "https://clinica.com.br", "cid": "99",
                         "rating": 4.5, "ratingCount": 12}]}
    pages, seen = [page1, page2], []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body["gl"] == "br" and request.headers["X-API-KEY"] == "k"
        return httpx.Response(200, json=pages[body["page"] - 1])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = D.SerperPlaces()
    out = await provider.fetch(client, {"serper_api_key": "k"},
                               D.DiscoveryQuery(term="loja", location="Franca, SP"))
    assert len(out) == 11 and len(seen) == 2
    assert out[0].has_website is False and out[0].domain == ""
    assert out[-1].domain == "clinica.com.br" and out[-1].review_count == 12
    assert out[-1].source_url == "https://maps.google.com/?cid=99"


def test_message_names_the_strongest_signal_and_signs():
    from harvey.br_messages import compose_message
    msg = compose_message({"company_name": "Padaria Pão Bom",
                           "signals": "NO_ONLINE_BOOKING;NO_WEBSITE",
                           "rating": 4.7, "review_count": 212},
                          sender="Tavim", company="TS Sites", style=0)
    assert "Padaria Pão Bom" in msg
    assert "Me chamo Tavim, da TS Sites, e trabalho criando sites" in msg
    assert "ainda não têm um site" in msg          # NO_WEBSITE wins
    assert "parabéns pela nota 4,7 com 212 avaliações" in msg
    assert "prévia de como ficaria o site de vocês" in msg
    assert msg == compose_message({"company_name": "Padaria Pão Bom",
                                   "signals": "NO_ONLINE_BOOKING;NO_WEBSITE",
                                   "rating": 4.7, "review_count": 212},
                                  sender="Tavim", company="TS Sites", style=0)


def test_three_styles_mix_across_a_list_and_stay_complete():
    from collections import Counter
    from harvey.br_messages import STYLES, compose_message, style_index
    lead = {"company_name": "Salão Bela", "signals": "WHATSAPP_ONLY_BOOKING",
            "rating": 4.9, "review_count": 80}
    msgs = [compose_message(lead, sender="Tavim", company="TS Sites", style=i)
            for i in range(len(STYLES))]
    assert len(STYLES) == 3 and len(set(msgs)) == 3
    for m in msgs:
        assert "Salão Bela" in m and "Tavim, da TS Sites" in m and ",." not in m
        assert "WhatsApp" in m and "4,9 com 80 avaliações" in m
        assert "prévia de como ficaria o agendamento online" in m and m.endswith("?")
    for st in STYLES:                       # every style covers every signal
        assert set(st["observations"]) == set(STYLES[0]["observations"])
    names = [f"Empresa {i}" for i in range(300)]
    assert min(Counter(style_index(n) for n in names).values()) > 70
    # The same business always gets the same style.
    assert compose_message(lead) == compose_message(lead)


def test_message_greeting_follows_the_clock():
    from datetime import datetime
    from harvey.br_messages import compose_message, greeting
    assert [greeting(datetime(2026, 1, 1, h)) for h in (4, 5, 11, 12, 17, 18, 23)] == \
        ["Boa noite", "Bom dia", "Bom dia", "Boa tarde", "Boa tarde", "Boa noite", "Boa noite"]
    msg = compose_message({"company_name": "Ótica Sol"}, now=datetime(2026, 1, 1, 9))
    assert msg.startswith("Bom dia, Ótica Sol")


def test_greeting_uses_the_name_a_person_would_say():
    from harvey.br_messages import short_name
    assert short_name("Dra Ana Lima | Botox | Preenchimento") == "Dra Ana Lima"
    assert short_name("Salão Bela em São Sebastião do Paraíso MG") == "Salão Bela"
    assert short_name("DENTISTA - Dra. Thaís Lacerda") == "Dra. Thaís Lacerda"
    assert short_name("Odonto Paraíso") == "Odonto Paraíso"
    assert short_name("São Sebastião do Paraíso") == "São Sebastião do Paraíso"


def test_message_without_signals_or_sender_is_still_usable():
    from harvey.br_messages import compose_message, wa_link
    msg = compose_message({"company_name": "Oficina do Zé", "rating": 4.0,
                           "review_count": 3})
    assert "Tavim" not in msg and "nota" not in msg
    assert msg.startswith(("Bom dia, Oficina do Zé", "Boa tarde, Oficina do Zé",
                           "Boa noite, Oficina do Zé"))
    assert msg.endswith("?") and msg.count("\n\n") == 3
    link = wa_link("+5516991234567", "Oi, tudo bem?")
    assert link == "https://wa.me/5516991234567?text=Oi%2C%20tudo%20bem%3F"


def test_html_page_embeds_the_board_and_is_injection_safe():
    import json as _json
    import re
    from harvey.leads import to_html
    rows = [{"id": "c1", "company_name": "Bar </script><script>alert(1)</script>",
             "industry": "bar", "phone": "(16) 99123-4567", "status": "negociando",
             "status_at": "2026-10-27", "whatsapp_message": "Oi!", "score": 60}]
    page = to_html(rows, title="Leads de Teste")
    assert "<title>Leads de Teste</title>" in page
    assert "window.LeadBoard" in page and ".lb-niche" in page
    # The data block cannot close the script tag early.
    assert page.count("</script>") == 2
    data = re.search(r"var leads = (\[.*?\]);\n", page, re.S).group(1)
    assert _json.loads(data)[0]["status"] == "negociando"


# ── booking detection for Brazilian sites ──

def _collector(html):
    from harvey.collectors.profile import ProfileCollector
    c = ProfileCollector.__new__(ProfileCollector)
    c.confirmed = {"NO_ONLINE_BOOKING", "WHATSAPP_ONLY_BOOKING"}

    async def fake_get(url):
        return html if url.rstrip("/").endswith("salao.com.br") else ""
    c._get = fake_get
    return c


async def _booking(html):
    c = _collector(html)
    obs = await c.profile_company("c1", "salao.com.br")
    return {o["signal_code"]: o["value_num"] for o in obs}


@pytest.mark.asyncio
@pytest.mark.parametrize("html", [
    '<a href="https://www.trinks.com/salao-x">Agende</a>',
    '<a href="https://booksy.com/pt-br/123">Reservar</a>',
    '<a href="https://www.doctoralia.com.br/dra-x">Consulta</a>',
    '<a href="/agenda">Agende já o seu horário</a>',
    '<button>Agendamento online</button>',
])
async def test_brazilian_booking_tools_count_as_booking(html):
    got = await _booking(f"<html><body>{html}"
                         '<a href="https://wa.me/5535999990000">WhatsApp</a></body></html>')
    assert got == {"NO_ONLINE_BOOKING": 0, "WHATSAPP_ONLY_BOOKING": 0}


@pytest.mark.asyncio
async def test_whatsapp_link_without_booking_tool_is_whatsapp_only():
    got = await _booking('<html><a href="https://wa.me/5535999990000">'
                         'Agende pelo WhatsApp</a></html>')
    assert got == {"NO_ONLINE_BOOKING": 1, "WHATSAPP_ONLY_BOOKING": 1}
    got = await _booking('<html><a href="https://wa.link/abc123">Fale conosco</a></html>')
    assert got == {"NO_ONLINE_BOOKING": 1, "WHATSAPP_ONLY_BOOKING": 1}
    got = await _booking("<html><p>Ligue para nós</p></html>")
    assert got == {"NO_ONLINE_BOOKING": 1, "WHATSAPP_ONLY_BOOKING": 0}


# ── score, false signals, niches ──

@pytest.mark.asyncio
async def test_signals_recorded_as_false_are_not_pitched_and_score_orders(state):
    from harvey.leads import niche_report
    from harvey.models.company import Company

    async def company(name, phone, domain="", industry="barbearia", **signals):
        cid = await state.add_company(Company(
            name=name, phone=phone, domain=domain,
            website=f"https://{domain}" if domain else "", industry=industry))
        await state.add_observations([
            {"company_id": cid, "signal_code": code, "collector": "test",
             "value_num": value} for code, value in signals.items()])
        return cid

    await company("Com agenda", "(35) 99111-1111", "a.com.br",
                  NO_ONLINE_BOOKING=0, WHATSAPP_ONLY_BOOKING=0,
                  REVIEW_RATING=4.9, REVIEW_COUNT=80)
    await company("Agenda no zap", "(35) 99222-2222", "b.com.br",
                  NO_ONLINE_BOOKING=1, WHATSAPP_ONLY_BOOKING=1,
                  REVIEW_RATING=4.8, REVIEW_COUNT=60, BLOG_STALE=30)
    await company("Sem site", "(35) 99333-3333", industry="dentista",
                  NO_WEBSITE=1, REVIEW_RATING=4.6, REVIEW_COUNT=25)

    rows = await collect_leads(state)
    by = {r["company_name"]: r for r in rows}
    assert by["Com agenda"]["signals"] == ""
    assert by["Agenda no zap"]["signals"] == "WHATSAPP_ONLY_BOOKING;NO_ONLINE_BOOKING"
    assert "pelo WhatsApp" in by["Agenda no zap"]["whatsapp_message"]
    assert [r["company_name"] for r in rows][-1] == "Com agenda"
    assert by["Sem site"]["score"] == 40 + 12 + 10 + 10
    assert by["Agenda no zap"]["score"] == 30 + 20 + 10 + 10

    niches = {n["niche"]: n for n in niche_report(rows)}
    assert niches["barbearia"]["total"] == 2
    assert niches["barbearia"]["no_booking"] == 1
    assert niches["dentista"]["no_website"] == 1


def test_link_in_bio_pages_are_not_websites():
    q = D.DiscoveryQuery(term="estética")
    for url in ("https://bio.site/clinica", "https://linkme.bio/x", "https://bit.ly/abc"):
        biz = D.SerperPlaces()._parse({"title": "X", "website": url, "cid": "1"}, q)
        assert biz.has_website is False and biz.domain == "", url

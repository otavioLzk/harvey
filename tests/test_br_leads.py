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
        for i in range(20)]}
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
    assert len(out) == 21 and len(seen) == 2
    assert out[0].has_website is False and out[0].domain == ""
    assert out[-1].domain == "clinica.com.br" and out[-1].review_count == 12
    assert out[-1].source_url == "https://maps.google.com/?cid=99"


def test_message_names_the_strongest_signal_and_signs():
    from harvey.br_messages import compose_message
    msg = compose_message({"company_name": "Padaria Pão Bom",
                           "signals": "NO_ONLINE_BOOKING;NO_WEBSITE",
                           "rating": 4.7, "review_count": 212},
                          sender="Tavim", company="TS Sites")
    assert "Padaria Pão Bom" in msg
    assert "Meu nome é Tavim, da TS Sites." in msg
    assert "ainda não têm um site" in msg          # NO_WEBSITE wins
    assert "Nota 4,7 com 212 avaliações" in msg
    assert msg == compose_message({"company_name": "Padaria Pão Bom",
                                   "signals": "NO_ONLINE_BOOKING;NO_WEBSITE",
                                   "rating": 4.7, "review_count": 212},
                                  sender="Tavim", company="TS Sites")


def test_message_without_signals_or_sender_is_still_usable():
    from harvey.br_messages import compose_message, wa_link
    msg = compose_message({"company_name": "Oficina do Zé", "rating": 4.0,
                           "review_count": 3})
    assert "Meu nome" not in msg and "Nota" not in msg
    assert msg.endswith("?")
    link = wa_link("+5516991234567", "Oi, tudo bem?")
    assert link == "https://wa.me/5516991234567?text=Oi%2C%20tudo%20bem%3F"


@pytest.mark.asyncio
async def test_html_page_escapes_and_has_buttons(state):
    from harvey.leads import to_html
    rows = [{"company_name": "Bar <b>do</b> João", "industry": "bar",
             "phone": "(16) 99123-4567", "address": "Centro", "maps_url": "",
             "signals": "NO_WEBSITE", "whatsapp_message": "Oi!",
             "whatsapp_link": "https://wa.me/5516991234567?text=Oi%21"},
            {"company_name": "Fixo", "industry": "", "phone": "(16) 3322-1100",
             "address": "", "maps_url": "", "signals": "",
             "whatsapp_message": "Oi!", "whatsapp_link": ""}]
    page = to_html(rows)
    assert "Bar &lt;b&gt;do&lt;/b&gt; João" in page
    assert page.count("Abrir no WhatsApp") == 1
    assert "sem site" in page and "Leads (2)" in page

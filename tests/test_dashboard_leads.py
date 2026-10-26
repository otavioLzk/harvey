"""Dashboard Leads tab: the list, who signs it, the contacted queue, terms."""

import asyncio
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import harvey.dashboard as dash
from harvey.models.company import Company
from harvey.state import StateManager


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "harvey.db"
        monkeypatch.setattr(dash, "DB_PATH", db)
        monkeypatch.setattr(dash, "WEB_DIR", Path(__file__).resolve().parent.parent / "harvey" / "web")
        with TestClient(dash.app) as c:
            c.db_path = db
            yield c


def _add(db, name, phone):
    async def go():
        state = StateManager(str(db))
        await state.init_db()
        return await state.add_company(Company(name=name, phone=phone, industry="barbearia"))
    return asyncio.run(go())


def test_leads_list_sign_and_mark_contacted(client):
    cid = _add(client.db_path, "Barbearia do Léo", "(35) 99811-2233")
    _add(client.db_path, "Fixo", "(35) 3531-2020")

    data = client.get("/api/leads").json()
    assert [l["company_name"] for l in data["leads"]][0] == "Barbearia do Léo"
    assert data["niches"][0]["niche"] == "barbearia"

    assert client.post("/api/leads/sender", json={"name": "Tavim", "company": ""}).json()["success"]
    lead = client.get("/api/leads").json()["leads"][0]
    assert "Meu nome é Tavim." in lead["whatsapp_message"]
    assert lead["contacted_at"] == ""

    r = client.post(f"/api/leads/{cid}/contacted", json={"contacted": True}).json()
    assert r["contacted_at"]
    lead = next(l for l in client.get("/api/leads").json()["leads"] if l["id"] == cid)
    assert lead["contacted_at"] == r["contacted_at"]

    client.post(f"/api/leads/{cid}/contacted", json={"contacted": False})
    lead = next(l for l in client.get("/api/leads").json()["leads"] if l["id"] == cid)
    assert lead["contacted_at"] == ""


def test_leads_csv_download(client):
    _add(client.db_path, "Salão Bela", "(35) 99722-1100")
    r = client.get("/api/export/leads.csv")
    assert r.status_code == 200
    assert r.content.startswith("﻿".encode())      # Excel reads the accents
    assert "Salão Bela" in r.content.decode("utf-8-sig")


def test_estimate_uses_terms_typed_in_the_tab(client):
    data = client.post("/api/discover/estimate", json={
        "provider": "osm", "cities": ["São Sebastião do Paraíso, MG"],
        "terms": ["barbearia", "dentista"]}).json()
    assert data["queries"] == ["barbearia São Sebastião do Paraíso, MG",
                               "dentista São Sebastião do Paraíso, MG"]


def test_leads_tab_is_in_the_page(client):
    html = client.get("/").text
    assert "showTab('leads'" in html and 'id="lead-list"' in html

import re
from pathlib import Path

import pytest

from app.db.seed import load_network_seed
from app.tools import network

RUNBOOKS_DIR = Path(__file__).resolve().parents[1] / "data" / "runbooks"
SEVERITY_ORDER = ["critical", "major", "minor", "warning"]


@pytest.fixture
def db(db_session):
    load_network_seed(db_session)
    return db_session


def test_seed_can_be_loaded_twice(db):
    counts = load_network_seed(db)

    assert counts == {"sites": 5, "devices": 8, "links": 13, "circuits": 8, "alarms": 17}


def test_active_alarms_exclude_cleared_and_sort_by_severity(db):
    result = network.get_active_alarms(db, site_code="SITE-SUR-02")

    severities = [a["severity"] for a in result["alarms"]]
    assert severities == sorted(severities, key=SEVERITY_ORDER.index)
    # Alarm 12 (Gi0/0/3 down yesterday) was cleared and must not show up.
    assert 12 not in [a["id"] for a in result["alarms"]]
    assert result["total_active"] == 4 and not result["truncated"]


def test_active_alarms_filters_are_case_insensitive(db):
    by_site = network.get_active_alarms(db, site_code=" site-este-04 ")
    by_device = network.get_active_alarms(db, device="SW-ESTE-04")

    assert by_site["total_active"] == 5
    assert {a["device"] for a in by_device["alarms"]} == {"sw-este-04"}


def test_active_alarms_reports_truncation(db):
    result = network.get_active_alarms(db, limit=3)

    assert result["returned"] == 3
    assert result["total_active"] == 14
    assert result["truncated"] is True


def test_active_alarms_limit_is_clamped(db):
    assert network.get_active_alarms(db, limit=0)["returned"] == 1
    assert network.get_active_alarms(db, limit=10_000)["returned"] == 14


def test_device_links_are_described_from_its_own_side(db):
    device = network.get_device(db, "sw-centro-03")

    to_este = next(link for link in device["links"] if link["remote_device"] == "sw-este-04")
    assert to_este["local_interface"] == "Te1/0/20"
    assert to_este["remote_interface"] == "Te1/1/1"
    assert to_este["status"] == "down"
    assert device["site"]["code"] == "SITE-CENTRO-03"


def test_device_shows_redundancy_peer_and_transit(db):
    device = network.get_device(db, "rtr-norte-02")

    assert device["redundancy_peer"] == "rtr-norte-01"
    transit = next(link for link in device["links"] if link["kind"] == "transit")
    assert transit["remote_device"] is None
    assert transit["remote_description"] == "Transit provider AS64510"


def test_unknown_device_returns_suggestions(db):
    result = network.get_device(db, "rtr-norte-2")

    assert result["found"] is False
    assert result["suggestions"] == ["rtr-norte-01", "rtr-norte-02"]


def test_site_counts_active_alarms_by_severity(db):
    site = network.get_site(db, "site-sur-02")

    assert site["found"] is True
    assert site["active_alarms_by_severity"] == {"major": 3, "minor": 1}
    assert site["backup_power_hours"] == 4


def test_unknown_site_returns_suggestions(db):
    assert network.get_site(db, "Site Sur")["suggestions"] == ["SITE-SUR-02"]


def test_find_circuit_by_partial_customer_name_includes_port_alarms(db):
    result = network.find_circuits(db, "distribuidora")

    (circuit,) = result["circuits"]
    assert circuit["circuit_id"] == "SUR-2210"
    assert [a["type"] for a in circuit["active_alarms_on_access_port"]] == ["link_down"]


def test_find_circuit_by_id_is_case_insensitive(db):
    (circuit,) = network.find_circuits(db, "este-4471")["circuits"]

    assert circuit["customer"] == "Ferretería Los Andes"
    assert circuit["active_alarms_on_access_port"][0]["type"] == "onu_los"


def test_circuit_without_alarms_has_empty_list(db):
    (circuit,) = network.find_circuits(db, "Clínica San Rafael")["circuits"]

    assert circuit["active_alarms_on_access_port"] == []


def test_unknown_circuit(db):
    assert network.find_circuits(db, "no existe") == {
        "found": False,
        "query": "no existe",
        "circuits": [],
    }


@pytest.mark.parametrize("path", sorted(RUNBOOKS_DIR.glob("RB-*.md")), ids=lambda p: p.name)
def test_runbooks_have_title_and_scope(path):
    text = path.read_text(encoding="utf-8")

    assert re.match(r"# RB-\d{3} ", text)
    assert "- Applies to" in text
    assert "## Steps" in text

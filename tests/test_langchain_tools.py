import json
from contextlib import nullcontext

import pytest

from app.db.seed import load_network_seed
from app.tools.langchain_tools import build_network_tools


@pytest.fixture
def tools(db_session):
    load_network_seed(db_session)
    # Every tool call reuses the test session, which is rolled back after the test.
    return {t.name: t for t in build_network_tools(lambda: nullcontext(db_session))}


def test_tool_names_and_descriptions_for_the_model(tools):
    assert set(tools) == {"get_active_alarms", "get_device", "get_site", "find_circuits"}
    for t in tools.values():
        assert len(t.description) > 60, f"{t.name} needs a description the model can act on"


def test_argument_descriptions_come_from_the_docstrings(tools):
    schema = tools["find_circuits"].args_schema.model_json_schema()

    assert "customer name" in schema["properties"]["query"]["description"]


def test_optional_filters_are_optional(tools):
    schema = tools["get_active_alarms"].args_schema.model_json_schema()

    assert schema.get("required", []) == []


def test_tools_return_compact_json(tools):
    raw = tools["find_circuits"].invoke({"query": "distribuidora"})

    assert ": " not in raw and ", " not in raw.split('"message"')[0]
    result = json.loads(raw)
    assert result["circuits"][0]["circuit_id"] == "SUR-2210"


def test_alarm_tool_passes_filters_through(tools):
    result = json.loads(tools["get_active_alarms"].invoke({"device": "sw-este-04", "limit": 2}))

    assert result["returned"] == 2
    assert result["truncated"] is True

"""Read-only MCP server (stdio) over the Explainer tools and the API's plan cache.

The plan service runs on the sample data only (no processed data, no trained models, no LLM key), like
``test_api.py``. Every MCP tool result is compared with :class:`ExplainerTools` on the same cached plan.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client.client import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402
from test_api import DEMO_DAY, SAMPLE_DIR, tiny_backtest  # noqa: E402

from energy_brain.api.models import last_plan_day  # noqa: E402
from energy_brain.api.service import PlanService  # noqa: E402
from energy_brain.api.settings import ApiSettings  # noqa: E402
from energy_brain.explainer.tools import CONDITIONS, TOOL_DECLARATIONS, TOOL_NAMES, ExplainerTools  # noqa: E402
from energy_brain.mcp_server import server as mcp_server  # noqa: E402
from energy_brain.mcp_server.server import DAY_TOOL_NAMES, GridPilotMCP, build_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEIGHT = 0.5

#: Example arguments for every Explainer tool (beyond date and weight).
TOOL_ARGS: dict[str, dict] = {
    "get_plan_summary": {},
    "get_slot": {"time": "19:00"},
    "get_slot_range": {"start": "17:00", "end": "21:00"},
    "find_slots": {"condition": "battery_discharging"},
    "get_forecast": {"start": "06:00", "end": "18:00"},
    "get_signals": {},
    "get_assets": {},
    "get_risk_log": {},
    "get_forecast_note": {},
    "get_backtest_totals": {},
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def dirs(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("mcp")
    data = base / "data"
    shutil.copytree(SAMPLE_DIR, data / "sample")  # no data/processed
    (base / "models").mkdir()  # no trained models
    report = base / "backtest.json"
    report.write_text(json.dumps(tiny_backtest()), encoding="utf-8")
    days = base / "demo_days.yaml"
    days.write_text(f'days:\n  - {{date: "{DEMO_DAY}", label: "Demo day", demo: true}}\n', encoding="utf-8")
    return {"base": base, "data": data, "models": base / "models", "backtest": report, "days": days}


def settings_for(dirs) -> ApiSettings:
    return ApiSettings(
        warmup=False,
        data_dir=dirs["data"],
        models_dir=dirs["models"],
        backtest_path=dirs["backtest"],
        demo_days_path=dirs["days"],
        demo_answers_path=dirs["base"] / "no_answers.json",
    )


@pytest.fixture(scope="module")
def service(dirs) -> PlanService:
    return PlanService(settings_for(dirs))


@pytest.fixture(scope="module")
def app(service) -> GridPilotMCP:
    return GridPilotMCP(service)


def reference(service: PlanService, name: str, args: dict) -> dict:
    """What the in-app Explainer's tool returns for the same plan, as JSON."""
    entry, _ = service.get_plan(date.fromisoformat(DEMO_DAY), WEIGHT)
    return json.loads(json.dumps(ExplainerTools(entry.context).call(name, args)))


def escaped(text: str) -> str:
    return text.replace("(", r"\(").replace(")", r"\)").replace("[", r"\[").replace("]", r"\]")


# ---------------------------------------------------------------------------------------------- schemas


def test_tool_list_is_list_days_plus_every_explainer_tool(app):
    names = [t.name for t in app.tools()]
    assert names == ["list_days", *TOOL_NAMES]
    assert DAY_TOOL_NAMES == TOOL_NAMES


@pytest.mark.parametrize("decl", [d["function"] for d in TOOL_DECLARATIONS], ids=lambda d: d["name"])
def test_tool_schema_is_the_explainer_declaration_plus_date_and_weight(app, decl):
    tool = next(t for t in app.tools() if t.name == decl["name"])
    schema, params = tool.input_schema, decl["parameters"]
    assert tool.description == decl["description"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    for key, spec in params.get("properties", {}).items():
        assert schema["properties"][key] == spec
    assert set(schema["properties"]) == {"date", "weight", *params.get("properties", {})}
    assert schema["required"] == ["date", *params.get("required", [])]
    assert schema["properties"]["weight"]["minimum"] == 0 and schema["properties"]["weight"]["maximum"] == 1


def test_every_tool_is_marked_read_only(app):
    for tool in app.tools():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


# ---------------------------------------------------------------------------------------------- results


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_tool_result_equals_the_explainer_tool(app, service, name):
    args = TOOL_ARGS[name]
    result = app.call(name, {"date": DEMO_DAY, "weight": WEIGHT, **args})
    assert result == reference(service, name, args)


def test_weight_defaults_to_the_balanced_plan(app, service):
    assert app.call("get_plan_summary", {"date": DEMO_DAY}) == reference(service, "get_plan_summary", {})


def test_list_days_matches_the_api_day_list(app, service):
    days = app.call("list_days", {})
    assert days == json.loads(service.days().model_dump_json())
    assert DEMO_DAY in [d["date"] for d in days["days"]]


@pytest.mark.parametrize(
    "args, message",
    [
        ({}, "missing argument(s) ['date']"),
        ({"date": "2024-13-01"}, "date must be YYYY-MM-DD"),
        ({"date": "2021-12-31"}, "date must be between 2022-01-01"),
        ({"date": DEMO_DAY, "weight": 1.5}, "weight must be a number from 0 to 1"),
        ({"date": DEMO_DAY, "weight": "high"}, "weight must be a number from 0 to 1"),
        ({"date": DEMO_DAY, "weight": True}, "weight must be a number from 0 to 1"),
        ({"date": DEMO_DAY, "time": "19:00"}, "unknown argument(s) ['time']"),
    ],
)
def test_bad_day_arguments_are_rejected(app, args, message):
    with pytest.raises(mcp_server.ToolInputError, match=escaped(message)):
        app.call("get_plan_summary", args)


def test_day_after_tomorrow_is_rejected(app):
    later = date.fromordinal(last_plan_day().toordinal() + 1)
    with pytest.raises(mcp_server.ToolInputError, match="date must be between"):
        app.call("get_signals", {"date": later.isoformat()})


@pytest.fixture
def no_planning(dirs, monkeypatch) -> GridPilotMCP:
    """A server whose plan service fails the test if it is asked to plan."""
    service = PlanService(settings_for(dirs))

    def must_not_plan(*args, **kwargs):
        pytest.fail("get_plan() was called before the tool arguments were validated")

    monkeypatch.setattr(service, "get_plan", must_not_plan)
    return GridPilotMCP(service)


@pytest.mark.parametrize(
    "name, args, message",
    [
        ("find_slots", {"condition": "sunny"}, "find_slots: condition must be one of"),  # enum
        ("get_slot", {}, "get_slot: missing argument(s) ['time']"),  # missing
        ("get_slot_range", {"start": "17:00"}, "get_slot_range: missing argument(s) ['end']"),  # missing
        ("get_slot", {"time": 1900}, "get_slot: time must be a string"),  # type
        ("find_slots", {"condition": 3}, "find_slots: condition must be a string"),  # type
        ("get_plan_summary", {"time": "19:00"}, "get_plan_summary: unknown argument(s) ['time']"),  # unknown
        ("get_forecast", {"start": "06:00", "end": "18:00", "step": 1}, "unknown argument(s) ['step']"),
    ],
)
def test_schema_errors_are_rejected_before_planning(no_planning, name, args, message):
    with pytest.raises(mcp_server.ToolInputError, match=escaped(message)):
        no_planning.call(name, {"date": DEMO_DAY, "weight": WEIGHT, **args})


def test_valid_arguments_still_reach_the_planner(dirs, monkeypatch):
    service = PlanService(settings_for(dirs))
    calls = []
    real = service.get_plan
    monkeypatch.setattr(service, "get_plan", lambda *a: calls.append(a) or real(*a))
    GridPilotMCP(service).call("find_slots", {"date": DEMO_DAY, "condition": "outage"})
    assert calls == [(date.fromisoformat(DEMO_DAY), WEIGHT)]


def test_time_values_are_still_checked_by_the_explainer_after_planning(dirs, monkeypatch):
    """Clock parsing and range checks need the plan's slot grid, so they stay in ExplainerTools."""
    service = PlanService(settings_for(dirs))
    calls = []
    real = service.get_plan
    monkeypatch.setattr(service, "get_plan", lambda *a: calls.append(a) or real(*a))
    with pytest.raises(mcp_server.ToolInputError, match="is not HH:MM"):
        GridPilotMCP(service).call("get_slot", {"date": DEMO_DAY, "time": "noon"})
    assert len(calls) == 1


def test_explainer_argument_errors_pass_through(app):
    with pytest.raises(mcp_server.ToolInputError, match="condition must be one of"):
        app.call("find_slots", {"date": DEMO_DAY, "condition": "sunny"})
    with pytest.raises(mcp_server.ToolInputError, match="is not HH:MM"):
        app.call("get_slot", {"date": DEMO_DAY, "time": "noon"})


def test_unknown_tool_is_rejected(app):
    with pytest.raises(mcp_server.ToolInputError, match="unknown tool 'replan'"):
        app.call("replan", {"date": DEMO_DAY})


def test_list_days_takes_no_arguments(app):
    with pytest.raises(mcp_server.ToolInputError, match="unknown argument"):
        app.call("list_days", {"date": DEMO_DAY})


def test_solving_a_plan_writes_nothing_to_stdout(dirs, capfd):
    fresh = GridPilotMCP(PlanService(settings_for(dirs)))
    capfd.readouterr()
    fresh.call("get_plan_summary", {"date": DEMO_DAY, "weight": 0.3})
    assert capfd.readouterr().out == ""


# ------------------------------------------------------------------------------------ resources, prompts


def test_unknown_resource_and_prompt_are_rejected(app):
    with pytest.raises(mcp_server.ToolInputError, match="unknown resource"):
        app.read_resource("gridpilot://secrets")
    with pytest.raises(mcp_server.ToolInputError, match="unknown prompt"):
        app.prompt("delete_everything", {})
    with pytest.raises(mcp_server.ToolInputError, match="missing argument"):
        app.prompt("outage_readiness", {})


def test_prompts_only_name_real_tools_and_conditions(app):
    text = app.prompt("outage_readiness", {"date": DEMO_DAY})
    assert "find_slots" in text and DEMO_DAY in text
    for word in ("outage", "battery_discharging", "generator_on"):
        assert word in text and word in CONDITIONS


# ---------------------------------------------------------------------------------------------- protocol


@pytest.mark.anyio
async def test_protocol_tools_resources_and_prompts(app, service):
    async with Client(build_server(app)) as client:
        tools = await client.list_tools()
        assert [t.name for t in tools.tools] == ["list_days", *TOOL_NAMES]

        ok = await client.call_tool("find_slots", {"date": DEMO_DAY, "condition": "outage"})
        assert ok.is_error is False
        assert ok.structured_content == reference(service, "find_slots", {"condition": "outage"})
        assert json.loads(ok.content[0].text) == ok.structured_content

        bad = await client.call_tool("find_slots", {"date": DEMO_DAY, "condition": "sunny"})
        assert bad.is_error is True
        assert "condition must be one of" in bad.content[0].text

        resources = await client.list_resources()
        uris = sorted(str(r.uri) for r in resources.resources)
        assert uris == ["gridpilot://backtest", "gridpilot://caveats", "gridpilot://site"]
        caveats = await client.read_resource("gridpilot://caveats")
        assert json.loads(caveats.contents[0].text)["caveats"] == tiny_backtest()["caveats"]
        site = await client.read_resource("gridpilot://site")
        assert site.contents[0].text == (ROOT / "config" / "site.yaml").read_text(encoding="utf-8")

        prompts = await client.list_prompts()
        assert sorted(p.name for p in prompts.prompts) == [
            "compare_with_baseline",
            "explain_plan",
            "outage_readiness",
        ]
        got = await client.get_prompt("explain_plan", {"date": DEMO_DAY, "weight": "0.5"})
        text = got.messages[0].content.text
        assert DEMO_DAY in text and "get_plan_summary" in text and "gridpilot://caveats" in text


@pytest.mark.anyio
async def test_unexpected_errors_do_not_leak_details(app, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal path /root/.env")

    monkeypatch.setattr(app, "call", boom)
    async with Client(build_server(app)) as client:
        res = await client.call_tool("get_assets", {"date": DEMO_DAY})
    assert res.is_error is True
    assert "secret" not in res.content[0].text and "internal error" in res.content[0].text


# ---------------------------------------------------------------------------------------------- stdio


@pytest.mark.anyio
async def test_stdio_server_runs_without_any_llm_key(dirs):
    env = {k: v for k, v in os.environ.items() if "KEY" not in k and not k.startswith("LLM_")}
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "energy_brain.mcp_server",
            "--data-dir",
            str(dirs["data"]),
            "--models-dir",
            str(dirs["models"]),
            "--backtest",
            str(dirs["backtest"]),
            "--demo-days",
            str(dirs["days"]),
        ],
        env=env,
    )
    async with Client(params) as client:
        assert client.server_info.name == "gridpilot"
        res = await client.call_tool("get_plan_summary", {"date": DEMO_DAY, "weight": WEIGHT})
    assert res.is_error is False
    assert res.structured_content["date"] == DEMO_DAY

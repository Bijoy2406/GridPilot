"""Read-only MCP server: the Explainer tools over the API's plan cache, for any MCP client (stdio).

Nothing new is computed here. :class:`GridPilotMCP` turns ``(date, weight)`` into a cached plan with
:class:`PlanService` (the same cache and agents as the web API) and answers with :class:`ExplainerTools`
(the same tools the in-app Explainer calls). Tool schemas are the Explainer's ``TOOL_DECLARATIONS`` plus
``date`` and ``weight``, so the two can never drift apart.

* **Read only.** No tool plans a what-if, changes a plan or writes anything; there is no LLM call and no key.
* **Errors** are returned as MCP tool errors with a short message; unexpected failures are logged to stderr
  and reported as "internal error" without details.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import date
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server

from energy_brain import __version__
from energy_brain.api.models import FIRST_PLAN_DAY, last_plan_day
from energy_brain.api.service import PlanService
from energy_brain.config import DEFAULT_SITE_CONFIG
from energy_brain.explainer.tools import TOOL_DECLARATIONS, TOOL_NAMES, ExplainerTools, ToolArgumentError

logger = logging.getLogger(__name__)

SERVER_NAME = "gridpilot"
#: Weight used when a client leaves it out: the balanced plan the dashboard opens with.
DEFAULT_WEIGHT = 0.5
#: Explainer tools exposed per plan (all of them; each takes ``date`` and ``weight`` in addition).
DAY_TOOL_NAMES = TOOL_NAMES

_DATE = {
    "type": "string",
    "description": "planning day YYYY-MM-DD, from 2022-01-01 to tomorrow (site time); see list_days",
}
_WEIGHT = {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "default": DEFAULT_WEIGHT,
    "description": "cost/carbon weight: 1 = cheapest, 0 = cleanest; rounded to 0.01",
}
_JSON = "application/json"
_READ_ONLY = types.ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

CAVEATS = (
    "Synthetic load, simulated PV and synthetic outages; results are a historical replay, "
    "not measured savings from a real site."
)
INSTRUCTIONS = (
    "GridPilot AI plans a simulated Dhaka garment factory's solar, battery, EV charging and diesel "
    "generator. Every tool is read-only. Call list_days first, then the plan tools with a date and weight. "
    "Quote only numbers returned by the tools and mention the caveats in gridpilot://caveats."
)


class ToolInputError(ValueError):
    """A client called a tool, resource or prompt with a bad name or bad arguments."""


def _day_schema(parameters: dict[str, Any]) -> dict[str, Any]:
    """An Explainer tool's declared parameters plus ``date`` (required) and ``weight`` (default 0.5)."""
    params = copy.deepcopy(parameters)
    return {
        "type": "object",
        "properties": {"date": dict(_DATE), "weight": dict(_WEIGHT), **params.get("properties", {})},
        "required": ["date", *params.get("required", [])],
        "additionalProperties": False,
    }


def _json(value: Any) -> Any:
    """``value`` as plain JSON types (dates and numpy scalars converted the way the API does)."""
    return json.loads(json.dumps(value, default=str))


class GridPilotMCP:
    """Tools, resources and prompts over one :class:`PlanService` (synchronous; the server runs it in a
    worker thread)."""

    def __init__(self, service: PlanService) -> None:
        self.service = service
        self._tools = [
            types.Tool(
                name="list_days",
                description="Planning days: demo days and tomorrow, with outages, holidays, forecast tier.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=_READ_ONLY,
            ),
            *(
                types.Tool(
                    name=d["function"]["name"],
                    description=d["function"]["description"],
                    input_schema=_day_schema(d["function"]["parameters"]),
                    annotations=_READ_ONLY,
                )
                for d in TOOL_DECLARATIONS
            ),
        ]

    # ------------------------------------------------------------------ tools

    def tools(self) -> list[types.Tool]:
        return list(self._tools)

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Run tool ``name``; raises :class:`ToolInputError` for a bad name or bad arguments."""
        args = dict(arguments or {})
        if name == "list_days":
            if args:
                raise ToolInputError(f"list_days: unknown argument(s) {sorted(args)}")
            return _json(self.service.days().model_dump(mode="json"))
        if name not in DAY_TOOL_NAMES:
            raise ToolInputError(f"unknown tool {name!r}; available: list_days, {', '.join(DAY_TOOL_NAMES)}")
        if "date" not in args:
            raise ToolInputError(f"{name}: missing argument(s) ['date']")
        day = self._day(args.pop("date"))
        weight = self._weight(args.pop("weight", DEFAULT_WEIGHT))
        entry, _ = self.service.get_plan(day, weight)
        try:
            return _json(ExplainerTools(entry.context).call(name, args))
        except ToolArgumentError as exc:
            raise ToolInputError(str(exc)) from None

    @staticmethod
    def _day(value: Any) -> date:
        """Same range as the web API's ``/plan`` (``_DayRequest``)."""
        try:
            day = date.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            day = None
        if day is None:
            raise ToolInputError(f"date must be YYYY-MM-DD, got {value!r}")
        last = last_plan_day()
        if not FIRST_PLAN_DAY <= day <= last:
            raise ToolInputError(
                f"date must be between {FIRST_PLAN_DAY.isoformat()} and {last.isoformat()} (tomorrow)"
            )
        return day

    @staticmethod
    def _weight(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
            raise ToolInputError(f"weight must be a number from 0 to 1, got {value!r}")
        return float(value)

    # ------------------------------------------------------------------ resources

    RESOURCES = {
        "gridpilot://caveats": ("caveats", "Data caveats every answer must mention", _JSON),
        "gridpilot://site": ("site", "The simulated site: assets, limits, tariffs (site.yaml)", "text/yaml"),
        "gridpilot://backtest": ("backtest", "2024 backtest summary vs the two baselines", _JSON),
    }

    def resources(self) -> list[types.Resource]:
        return [
            types.Resource(uri=uri, name=name, description=desc, mime_type=mime)
            for uri, (name, desc, mime) in self.RESOURCES.items()
        ]

    def read_resource(self, uri: str) -> tuple[str, str]:
        """``(text, mime type)`` of resource ``uri``."""
        if uri not in self.RESOURCES:
            raise ToolInputError(f"unknown resource {uri!r}; available: {', '.join(self.RESOURCES)}")
        mime = self.RESOURCES[uri][2]
        bt = self.service.backtest()
        if uri == "gridpilot://site":
            return DEFAULT_SITE_CONFIG.read_text(encoding="utf-8"), mime
        if uri == "gridpilot://caveats":
            caveats = (bt or {}).get("caveats") or [CAVEATS]
            return json.dumps({"summary": CAVEATS, "caveats": caveats}, indent=1), mime
        if not bt:
            return json.dumps({"available": False, "reason": "no backtest report loaded"}), mime
        keep = ("report", "caveats", "headline", "summary")
        return json.dumps(_json({k: bt[k] for k in keep if k in bt}), indent=1), mime

    # ------------------------------------------------------------------ prompts

    PROMPTS: dict[str, tuple[str, list[tuple[str, str, bool]]]] = {
        "explain_plan": (
            "Explain one day's plan in plain words, with numbers from the tools only.",
            [("date", "planning day YYYY-MM-DD", True), ("weight", "0 = cleanest .. 1 = cheapest", False)],
        ),
        "outage_readiness": (
            "Check how the plan prepares for the day's grid outages.",
            [("date", "planning day YYYY-MM-DD", True)],
        ),
        "compare_with_baseline": (
            "Compare the plan with the backtest baselines for one day.",
            [("date", "planning day YYYY-MM-DD", True)],
        ),
    }

    _RULES = (
        "Use only numbers returned by the GridPilot tools; do not calculate new totals. Say that the data is "
        "synthetic or simulated (read gridpilot://caveats). The plan is read-only: do not suggest the tools "
        "changed anything."
    )

    def prompts(self) -> list[types.Prompt]:
        return [
            types.Prompt(
                name=name,
                description=desc,
                arguments=[types.PromptArgument(name=a, description=d, required=r) for a, d, r in args],
            )
            for name, (desc, args) in self.PROMPTS.items()
        ]

    def prompt(self, name: str, arguments: dict[str, str] | None) -> str:
        if name not in self.PROMPTS:
            raise ToolInputError(f"unknown prompt {name!r}; available: {', '.join(self.PROMPTS)}")
        args = dict(arguments or {})
        missing = [a for a, _, required in self.PROMPTS[name][1] if required and not args.get(a)]
        if missing:
            raise ToolInputError(f"{name}: missing argument(s) {missing}")
        day = args["date"]
        weight = args.get("weight") or str(DEFAULT_WEIGHT)
        on = f'date "{day}" and weight {weight}'
        if name == "explain_plan":
            task = (
                f"Explain the GridPilot plan for {on}. Call get_plan_summary, then get_risk_log, and "
                "find_slots for battery_charging, battery_discharging and generator_on. Say when and why the "
                "battery charges and discharges and whether the generator runs."
            )
        elif name == "outage_readiness":
            task = (
                f"Check outage readiness for {on}. Call get_signals for the outage blocks, then find_slots "
                "for outage, battery_discharging and generator_on, and get_slot_range over each outage. Say "
                "how the load is covered during each outage and the battery state of charge before it."
            )
        else:
            task = (
                f"Compare the GridPilot plan with the baselines for {on}. Call get_plan_summary and "
                "get_backtest_totals; if the day is not in the backtest, say so and give only the year "
                "totals."
            )
        return f"{task}\n\n{self._RULES}"


# ---------------------------------------------------------------------------------------------- protocol


def _text_result(text: str, *, error: bool, structured: dict[str, Any] | None = None) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=structured, is_error=error
    )


def build_server(app: GridPilotMCP) -> Server:
    """The MCP protocol layer (list/call tools, resources, prompts) over ``app``."""

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=app.tools())

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            result = await anyio.to_thread.run_sync(app.call, params.name, params.arguments)
        except ToolInputError as exc:
            return _text_result(str(exc), error=True)
        except Exception:
            logger.exception("tool %s failed", params.name)
            return _text_result(f"{params.name}: internal error; see the server log", error=True)
        return _text_result(json.dumps(result), error=False, structured=result)

    async def list_resources(ctx, params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=app.resources())

    async def read_resource(ctx, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
        uri = str(params.uri)
        text, mime = await anyio.to_thread.run_sync(app.read_resource, uri)
        content = types.TextResourceContents(uri=uri, mime_type=mime, text=text)
        return types.ReadResourceResult(contents=[content])

    async def list_prompts(ctx, params) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=app.prompts())

    async def get_prompt(ctx, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        text = app.prompt(params.name, params.arguments)
        message = types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))
        return types.GetPromptResult(description=app.PROMPTS[params.name][0], messages=[message])

    return Server(
        SERVER_NAME,
        version=__version__,
        title="GridPilot AI",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )

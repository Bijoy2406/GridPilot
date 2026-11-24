# MCP server (read-only, stdio)

GridPilot AI ships a small [Model Context Protocol](https://modelcontextprotocol.io) server so an MCP client
(Claude Desktop, Claude Code, the MCP Inspector, ...) can ask about the day-ahead plans. It reuses the web API's
plan cache (`PlanService`) and the in-app Explainer's read-only tools (`ExplainerTools`); it computes nothing
new.

- **Read only.** No tool changes a plan, runs a what-if (cloud event, overrides) or writes anything.
- **No LLM and no key.** The server never calls Groq; `LLM_API_KEY` is not needed. The client's own model
  does the explaining.
- **Local only.** Transport is stdio: the client starts the server as a child process. There is no network
  endpoint and so no login.

## Install and run

```bash
pip install -e ".[mcp]"          # the pinned MCP SDK (mcp==2.3.0), same version as CI
python -m energy_brain.mcp_server
```

Real plans need `data/processed/` and `models/` ([data-sources.md](data-sources.md)); without them the server
runs on the sample-data fallback, like the API. Paths can be changed with `--data-dir`, `--models-dir`,
`--backtest` and `--demo-days`. stdout carries only the protocol; logs go to stderr.

### Claude Code

```bash
claude mcp add gridpilot -- python -m energy_brain.mcp_server
```

Run it from the repository root (or pass absolute paths), with the Python environment that has the `mcp`
extra.

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "gridpilot": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "energy_brain.mcp_server"],
      "cwd": "/path/to/GridPilot"
    }
  }
}
```

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector python -m energy_brain.mcp_server
```

## Tools

Every plan tool takes `date` (YYYY-MM-DD, 2022-01-01 to tomorrow, the same range as `POST /plan`) and
`weight` (0 = cleanest, 1 = cheapest, default 0.5). The rest of each schema is the Explainer's
`TOOL_DECLARATIONS` unchanged (a test keeps them identical).

| Tool | Returns |
| --- | --- |
| `list_days` | Planning days: demo days and tomorrow, outages, holidays, forecast tier (same as `GET /days`) |
| `get_plan_summary` | Status, safe flag, Risk result, fallbacks, day totals, notes |
| `get_slot` (`time`) | One 15-minute slot: flows, battery SoC, tariff, outage, forecast, binding limits |
| `get_slot_range` (`start`, `end`) | Energy per flow, cost, CO2, SoC start/end/min/max over a range |
| `find_slots` (`condition`) | Time blocks where e.g. `generator_on`, `battery_discharging`, `outage` holds |
| `get_forecast` (`start`, `end`) | Solar and base-load P10/P50/P90 |
| `get_signals` | Tariff windows, outage blocks, grid CO2 factor, diesel price |
| `get_assets` | Battery, generator, grid, HVAC and EV limits |
| `get_risk_log` | Risk agent result: re-plans, reserve, stress scenario |
| `get_forecast_note` | Whether a forecast or signal fallback is in use, and why |
| `get_backtest_totals` | 2024 backtest vs the two baselines, and this date's row |

Bad arguments come back as an MCP tool error (`isError: true`) with a short message, e.g.
`find_slots: condition must be one of [...]`. Unexpected failures are logged to stderr and reported as
"internal error" without details.

## Resources and prompts

| Resource | Content |
| --- | --- |
| `gridpilot://caveats` | Synthetic-data and historical-replay caveats (from the backtest report) |
| `gridpilot://site` | `config/site.yaml`: the simulated site's assets, limits and tariffs |
| `gridpilot://backtest` | Backtest headline and summary |

Prompts `explain_plan(date, weight?)`, `outage_readiness(date)` and `compare_with_baseline(date)` tell the
client which tools to call and to quote only numbers the tools return, as the in-app Explainer does.

## Tests

`tests/test_mcp_server.py` checks that every tool schema matches `TOOL_DECLARATIONS`, that every tool result
equals `ExplainerTools` on the same cached plan, the error messages, the resources and prompts over the
protocol, that solving a plan writes nothing to stdout, and that the stdio server starts and answers with no
LLM key in the environment.

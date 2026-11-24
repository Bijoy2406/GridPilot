"""Run the read-only GridPilot AI MCP server over stdio.

    python -m energy_brain.mcp_server [--data-dir DIR] [--models-dir DIR] [--backtest FILE] [--demo-days FILE]

The paths default to the repository's ``data/``, ``models/``, ``reports/backtest.json`` and
``config/demo_days.yaml`` (the same as the web API). No LLM key is needed. stdout carries only the MCP
protocol; logs go to stderr.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from energy_brain.api.settings import ApiSettings


def settings_from(args: argparse.Namespace) -> ApiSettings:
    paths = {
        "data_dir": args.data_dir,
        "models_dir": args.models_dir,
        "backtest_path": args.backtest,
        "demo_days_path": args.demo_days,
    }
    return ApiSettings.from_env(warmup=False, **{k: v for k, v in paths.items() if v is not None})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m energy_brain.mcp_server", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--data-dir", type=Path, help="data folder (default: data/)")
    ap.add_argument("--models-dir", type=Path, help="trained models folder (default: models/)")
    ap.add_argument("--backtest", type=Path, help="backtest report (default: reports/backtest.json)")
    ap.add_argument("--demo-days", type=Path, help="demo days YAML (default: config/demo_days.yaml)")
    args = ap.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    import anyio
    from mcp.server.stdio import stdio_server

    from energy_brain.api.service import PlanService
    from energy_brain.mcp_server.server import GridPilotMCP, build_server

    server = build_server(GridPilotMCP(PlanService(settings_from(args))))

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())

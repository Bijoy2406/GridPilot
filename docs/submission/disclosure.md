# Tooling, IDE, memory/context files and MCP disclosure (issue #36)

Sections for the final submission portal. Everything under **Bijoy** was written from what he actually used and can be
pasted as it is. The **Asif** and **ovishkh (frontend)** blocks are marked `[TO FILL]`: each teammate must list only
what they really used (a missing or wrong disclosure can block Submit). Dates are Nov 2026.

## 1. Text to paste into the portal

> **How we built it.** A three-person team built Gridpilot AI with AI coding assistants under human control. The
> backend/agents lead (Bijoy) worked as an orchestrator: he wrote each prompt, ran the coding agent, reviewed and
> tested the result himself, and approved every commit, pull request and merge. No change reached `main` without a
> passing CI run (backend and web test suites, lint, type check). The product ships a small **read-only MCP server**
> (stdio) that exposes the same ten verified Explainer tools to any MCP client; the product is not an MCP client,
> and the in-app Explainer calls those tools through ordinary LLM function calling.

## 2. Tools and assistants used

### Bijoy (backend, agents, optimiser, deployment, final integration)

| Tool | Version / model | Used for |
| --- | --- | --- |
| **Claude Code** (desktop app) | Claude Opus 5.5 and Sonnet 5.5 (and Haiku 5.5 for short tasks) | Orchestrator and reviewer: planning, writing prompts for other agents, reading diffs, running tests, browser checks, hand-written fixes (dark theme finish, splash/skeleton screens, voice input and its recorder integration, chat polish, mobile fixes, deployment files, these documents) |
| **OpenAI Codex CLI** (`codex exec`) | gpt-6.1-sol, medium or high reasoning effort, workspace-write sandbox | Implementation agent for most features: the UI recolour and motion effects, floating chat widget, issues #22/#25/#26/#33 and the dark-theme refactor (see the prompt library) |
| **Google Antigravity CLI** (`agy`) | gemini-3.8-flash-high, sandbox mode, accept-edits | Removing the Bangla feature; flaky-test and refactor jobs earlier. Chosen because the Codex quota ran out |
| **Visual Studio Code** | - | Editor, port forwarding for team demos, terminals |
| **Git and GitHub CLI** (`gh`) | - | Branches, pull requests, CI results, issue handling |
| **Docker + nginx + certbot** | - | Deployment on a VPS (https://energybrain.xven.app) |
| **Groq API** | gpt-oss-120b, whisper-large-v3-turbo | Part of the product (see `provenance.md`), not a development tool |
| Python tooling | pytest, ruff, uv/venv, pyomo, HiGHS | Tests, lint, environment |
| Web tooling | Node 22, Vite, Vitest + Testing Library, ESLint, TypeScript | Tests, build, lint |
| **Web components and libraries copied in** | React Bits (via its public registry), Tweenly AI Recorder (MIT) | Credited in `web/src/fx` and `web/src/components/ui` |

Skills/plugins invoked inside Claude Code for this project: **ui-ux-pro-max** (one UI fix pass on the chat widget).
Other plugins that exist in the same environment (Vercel, Figma, Netlify, academic-writing and statistics tools) were
**not used** for this project.

### Asif A Khuda (data pipeline and forecasting) `[TO FILL]`

| Tool | Version / model | Used for |
| --- | --- | --- |
| `[e.g. IDE]` | | |
| `[e.g. AI assistant]` | | |

### ovishkh (frontend and deployment) `[TO FILL]`

| Tool | Version / model | Used for |
| --- | --- | --- |
| `[e.g. IDE]` | | |
| `[e.g. AI assistant]` | | |

### Token-optimisation tools

None used by Bijoy. `[Asif / ovishkh: list any, or write "none"]`

## 3. Memory, context and rules files

| File | Where | What it contained | Affects this project? |
| --- | --- | --- | --- |
| `Gridpilot AI — PRD.md` | repository root | Product requirements, demo script, judging alignment. Given to agents as the specification | Yes |
| `docs/interfaces.md`, `docs/data-sources.md`, `docs/site-spec.md`, `docs/api.md` | repository | Agent contracts, data provenance, site assumptions, API contract. The agents were told to read the relevant ones first | Yes |
| `prompts/*.md`, `prompts/explainer_demo_questions.yaml` | repository | The Explainer's prompts and the question set used to check it | Yes (it is part of the product) |
| Claude Code **project memory** (`MEMORY.md` and two project notes: `orchestrator-approval-workflow.md`, `agy-cli-usage.md`) | Bijoy's machine, outside the repository | Working rules: ask when unclear; never commit, push or merge without approval; how to run the `agy` CLI safely (sandbox, allowed commands) | Yes (process rules) |
| Claude Code **global instructions** (`~/.claude/CLAUDE.md`) and `~/AGENTS.md` | Bijoy's machine, outside the repository | One line each, about a separate knowledge-graph tool; no project content | No |
| Two other memory notes (a statistics-course note and a Stata bridge note) | Bijoy's machine | Unrelated to Gridpilot AI | No |

There is **no** `CLAUDE.md`, `AGENTS.md`, `.cursorrules` or similar rules file inside the repository. `[Asif / ovishkh:
add any rules or context files you used]`

## 4. MCP (Model Context Protocol)

**Does the product use MCP?** Yes, as a **server** only (built by us, `src/energy_brain/mcp_server/`,
[docs/mcp.md](../mcp.md)). It runs locally over stdio (`python -m energy_brain.mcp_server`), needs no LLM key
and is read-only: it exposes `list_days` and the Explainer's ten tools (`get_plan_summary`, `get_slot`,
`get_slot_range`, `find_slots`, `get_forecast`, `get_signals`, `get_assets`, `get_risk_log`,
`get_forecast_note`, `get_backtest_totals`) for a chosen date and weight, three resources
(`gridpilot://caveats`, `gridpilot://site`, `gridpilot://backtest`) and three prompts (`explain_plan`,
`outage_readiness`, `compare_with_baseline`). Tool schemas are the Explainer's declarations plus `date` and
`weight`; tests check that every result equals the in-app tool's result. The shipped web app is not an MCP
client: its Explainer uses standard LLM function calling with the same ten functions plus `refuse`.

**MCP servers used while building (Bijoy's Claude Code session):**

| Server | Why it was used | Tools it exposed that we used |
| --- | --- | --- |
| **Claude built-in browser** (the in-app browser tools) | To open the local app and the live site, check layouts at phone/tablet/desktop widths, read the page and run small scripts to measure elements, test the chat, voice recorder and demo mode | 6 tools: navigate, computer (clicks, typing, screenshots), find, javascript_tool, resize_window, browser_batch |

**Servers that were configured in the same environment but not used for the project:** Vercel, Figma, Netlify,
Stata, Codex image generation, a voice server. The 21st.dev "Magic" MCP server was tried for UI components but failed
to authenticate, so it was **not used**; the React Bits components were taken from that project's public registry
instead. `[Asif / ovishkh: list any MCP servers you used and what they did, or write "none"]`

## 5. Human control and quality gates

- Every pull request ran backend tests (pytest, 511), web tests (Vitest, 253), ESLint, TypeScript and the production
  build in GitHub Actions before merge.
- Agent output was never taken on trust: the lead re-ran the checks, read the diffs, recomputed key numbers
  independently (for example the monthly PDF figures from `reports/backtest.json`) and tested the result in a
  browser, including with a synthetic microphone for voice input.
- Agents were told not to commit; commits and merges were made only after the lead's approval.
- Problems found this way and fixed are recorded in the pull request descriptions (for example a false "flexible HVAC"
  claim in the footer, a chart palette that was not colour-blind safe, CI-only test failures).

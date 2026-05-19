# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeepTutor is an agent-native personalized tutoring platform with a Python backend (FastAPI), a Next.js frontend, and a CLI. It uses a two-layer model: **Tools** (Level 1, single-function LLM helpers) and **Capabilities** (Level 2, multi-step agent pipelines). All three entry points — CLI, WebSocket API, and Python SDK — route through the same `ChatOrchestrator`.

## Development Commands

### Install

```bash
pip install -e ".[dev]"           # backend + test/lint tools (implies [server])
cd web && npm install             # frontend (also: cd tutorbot-web && npm install)
```

Dependency extras (`pyproject.toml` `[project.optional-dependencies]`, mirrored in `requirements/*.txt`):
`[cli]` → LLM + RAG + doc parsing · `[server]` → `[cli]` + FastAPI/uvicorn · `[tutorbot]` → `[server]` + agent engine + channel SDKs · `[matrix]` Matrix channel (needs libolm) · `[math-animator]` Manim · `[dev]` test/lint · `[all]` everything.

First-time interactive setup (writes `.env`, picks LLM/embedding/search providers):
```bash
python scripts/start_tour.py
```

### Run (local)

```bash
python scripts/start_web.py            # backend (8001) + legacy web/ (3782)
python scripts/start_tutorbot_web.py   # backend (8001) + tutorbot-web/ (3000)  ← chatV2 branch

# Or manually:
python -m deeptutor.api.run_server   # backend only (alt: `deeptutor serve --port 8001`)
cd web && npm run dev -- -p 3782     # legacy frontend only
cd tutorbot-web && npm run dev       # new frontend only
```

There are **two frontends**: `web/` (original) and `tutorbot-web/` (newer, used on the `chatV2` branch — the currently active branch). The recent active work is in `tutorbot-web/`. **Heed `tutorbot-web/AGENTS.md`**: that app uses a pre-release Next.js whose APIs differ from public docs — read `tutorbot-web/node_modules/next/dist/docs/` before writing Next.js code there. Root-level `smoke-*.png` and `0[1-8]-*.png` files are throwaway smoke-test screenshots from that work, not committed assets.

### CLI

The `deeptutor` CLI (Typer, registered via `[project.scripts]`) is the agent-first entry point and shares `ChatOrchestrator` with the WebSocket and SDK paths:

```bash
deeptutor chat                                       # interactive REPL
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2=4" -t rag --kb my-kb
deeptutor kb create my-kb --doc textbook.pdf         # knowledge bases
deeptutor bot list                                   # TutorBot instances
deeptutor plugin list                                # registered tools + capabilities
deeptutor serve --port 8001                          # API server
```

Inside the REPL: `/cap`, `/tool on|off`, `/kb`, `/refs`, `/regenerate`. Full surface in `SKILL.md`.

### Tests

```bash
# Full smoke test suite (what CI runs)
pytest -q --import-mode=importlib \
  tests/api tests/cli tests/services/test_model_catalog.py \
  tests/services/test_path_service.py tests/services/memory \
  tests/services/session tests/tools

# Single test file
pytest -q --import-mode=importlib tests/core/test_stream_bus.py

# Import smoke check (fast sanity)
python -c "from deeptutor.runtime.orchestrator import ChatOrchestrator"
```

Test layout has separate suites you can target individually: `tests/api/`, `tests/cli/`, `tests/core/`, `tests/services/{config,embedding,llm,memory,model_selection,rag,search,session,tutorbot}`, `tests/agents/`, `tests/capabilities/`, `tests/tools/`, `tests/runtime/`, `tests/architecture/` (cross-cutting checks), `tests/scripts/`, `tests/knowledge/`, `tests/multi_user/`, `tests/tutorbot/`.

### Frontend

The two frontends have **different npm scripts** — don't assume parity:

```bash
# web/ (legacy, rich tooling)
cd web
npm run dev          # or: npm run dev:turbo (Turbopack)
npm run build
npm run lint
npm run test:node    # Node.js unit tests
npm run audit        # Playwright UI audit (also: audit:ui, audit:report)
npm run i18n:check   # parity + audit (also: i18n:audit:strict)
npm run perf:check   # route bundle budgets

# tutorbot-web/ (chatV2, minimal scripts)
cd tutorbot-web
npm run dev          # only dev/build/start/lint exist here
npm run build
npm run lint
```

### Lint & formatting

```bash
pre-commit run --all-files        # ruff, ruff format, prettier, bandit, detect-secrets, mypy
pre-commit run --all-files -q     # quiet mode
```

### Docker

```bash
docker compose up -d                              # build from source
docker compose -f docker-compose.ghcr.yml up -d  # pull official image
docker compose logs -f
```

`Dockerfile` builds the standard image; `Dockerfile.chatv2` is the variant used on the `chatV2` branch (pairs with `tutorbot-web/`).

### Update

```bash
python scripts/update.py   # safe fast-forward pull
```

## Architecture

### Request flow

```
CLI / WebSocket / Python SDK
        ↓
  ChatOrchestrator  (deeptutor/runtime/orchestrator.py)
        ↓
  CapabilityRegistry  →  selected Capability (e.g. deep_solve)
  ToolRegistry        →  tools the capability/LLM calls on demand
        ↓
  StreamBus  →  yields StreamEvent objects to the caller
```

### Core abstractions (`deeptutor/core/`)

| File | Purpose |
|------|---------|
| `context.py` | `UnifiedContext` — the single data object passed to every tool/capability |
| `stream.py` | `StreamEvent` / `StreamEventType` — unified streaming protocol |
| `stream_bus.py` | Async event fan-out |
| `tool_protocol.py` | `BaseTool` abstract class and `ToolDefinition` |
| `capability_protocol.py` | `BaseCapability` abstract class and `CapabilityManifest` |
| `errors.py` | Exception hierarchy (`DeepTutorError` → `ConfigurationError`, `ValidationError`, `LLMServiceError`, etc.) |
| `trace.py` | Tracing utilities |

### Module map

| Module | Purpose |
|--------|---------|
| `deeptutor/agents/` | Multi-agent pipelines powering capabilities. Each has its own `agents/` subdir, data models, pipeline, and YAML prompts under `prompts/{en,zh}/`. Modules: `chat`, `solve`, `question`, `research`, `math_animator`, `visualize`, `vision_solver`, `notebook`. |
| `deeptutor/capabilities/` | Capability implementations: `chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`, `_answer_now`. |
| `deeptutor/tools/` | Level-1 tools. Modules at root: `rag_tool.py`, `web_search.py`, `code_executor.py`, `reason.py`, `brainstorm.py`, `paper_search_tool.py`, `tex_chunker.py`, `tex_downloader.py`. Sub-packages: `builtin/` (built-in tool wrappers registered with `ToolRegistry`), `vision/` (block parsing, coordinate transforms, Geogebra validation), `question/` (exam mimic, PDF parsing, question extraction), `prompting/` (hints in en/zh). |
| `deeptutor/events/` | Application event bus (`EventBus`, `Event`, `EventType`) — separate layer from the streaming `StreamBus`. |
| `deeptutor/book/` | Book Engine — "living book" compiler with agents, block types, and prompts. |
| `deeptutor/co_writer/` | Co-Writer — multi-document Markdown workspace with prompts. |
| `deeptutor/knowledge/` | Knowledge base lifecycle management. |
| `deeptutor/tutorbot/` | TutorBot engine — agent, bus, channels, heartbeat, cron, skills, session, config. **Gotcha:** TutorBot maintains its own isolated tool registry separate from the main `ToolRegistry` — exposing a capability to a bot requires writing an `AdapterTool` subclass, not just registering with the global registry. |
| `deeptutor/multi_user/` | Multi-user isolation — auth, grants, per-user workspaces. |
| `deeptutor/api/` | FastAPI app (`main.py`), routers (key: `routers/unified_ws.py` — WebSocket `/api/v1/ws`), utilities. |
| `deeptutor/runtime/` | `ChatOrchestrator`, `registry/` (auto-discover on import), `bootstrap/`, `RunMode`. |
| `deeptutor/config/` | Runtime configuration loader. |
| `deeptutor/logging/` | Structured logging with adapters, handlers, and stats. |
| `deeptutor/utils/` | Shared utilities (network, etc.). |
| `deeptutor/app/` | Application wiring layer. |
| `deeptutor_cli/` | CLI package (separate from `deeptutor/`). |

### Services (`deeptutor/services/`)

| Service | Description |
|---------|-------------|
| `llm/` | Provider-agnostic LLM client. Prefer factory functions `complete`/`stream` over `LLMClient` directly. Providers under `provider_core/` and `providers/`. Registration via `provider_registry.py`. |
| `embedding/` | Embedding provider adapters (OpenAI, Cohere, Jina, Ollama, vLLM, custom) |
| `rag/` | LlamaIndex-backed RAG pipeline |
| `memory/` | User summary + profile persistence |
| `session/` | SQLite-backed session/conversation store |
| `search/` | Web search provider abstraction (Brave, Tavily, Serper, Jina, SearXNG, DuckDuckGo, Perplexity) |
| `prompt/` | `PromptManager` singleton — YAML prompt loading with language fallbacks (`zh → cn → en`) |
| `config/` | `EnvStore` (`.env` loader), runtime config |
| `skill/` | User-defined skill (SKILL.md) loading |
| `tutorbot/` | nanobot-based TutorBot manager |
| `model_selection/` | Model catalog and selection |
| `notebook/` | Notebook CRUD |
| `settings/` | User settings persistence |
| `storage/` | File storage abstraction |
| `setup/` | First-run setup and environment checks |

### Prompt system

All agent prompts live as YAML files under `deeptutor/agents/<module>/prompts/{en,zh}/`. Loaded via `PromptManager` (singleton), which handles language fallbacks (`zh → cn → en`). Prompts are externalized from Python — edit YAML, not agent code, to change system prompts.

### Frontend (`web/` and `tutorbot-web/`)

Two Next.js App Router frontends coexist: `web/` (the original; pages under `web/app/`, components under `web/components/`, state via React Context in `web/context/`, i18n in `web/i18n/` + `web/locales/`, Playwright audit tests) and `tutorbot-web/` (the newer one used on `chatV2`). Both use Next.js 16 / React 19. **`tutorbot-web/` uses a pre-release Next.js whose APIs differ from training data — always consult `tutorbot-web/node_modules/next/dist/docs/` before writing code there.**

### Multi-user layout (`multi-user/`)

Per-user workspaces are stored under `multi-user/u_<hex>/` (knowledge bases, sessions, notebooks, etc.), with auth/grants/audit under `multi-user/_system/`. The `deeptutor/multi_user/` Python package implements the isolation; the on-disk layout is what you'll see when debugging user-specific issues.

## Extending the System

### Add a new Tool

1. Create `deeptutor/tools/<name>.py` extending `BaseTool`.
2. Register it in `ToolRegistry` (`deeptutor/runtime/registry/tool_registry.py`).

### Add a new Capability

1. Create `deeptutor/capabilities/<name>.py` with a class extending `BaseCapability` that implements `async def run(self, context, stream_bus)`.
2. Define a `CapabilityManifest` with `name`, `description`, `stages`, and `tools_used`.
3. The `CapabilityRegistry` auto-discovers it on import.

### Add a new LLM provider

Add a provider class under `deeptutor/services/llm/provider_core/` and register it in `deeptutor/services/llm/provider_registry.py`.

## Branching & PR Rules

- **Do not PR to `main`**. Target `dev` for features/fixes, `multi-user` for multi-tenant work.
- Commit types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- Python: type hints required, PEP 8 (enforced by Ruff), Google-style docstrings, `pathlib.Path` for paths, `shell=False` in subprocesses.
- CI runs `pre-commit` strictly — local hooks may only warn.

## Configuration

Runtime config lives in `data/user/settings/main.yaml`. LLM/embedding/search credentials in `.env` (copy `.env.example`). Key env vars: `LLM_BINDING`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_HOST`, `EMBEDDING_*`, `SEARCH_PROVIDER`, `SEARCH_API_KEY`.

Agent stage token limits are configurable in `agents.yaml` (per-stage, defaults to 8000 tokens).

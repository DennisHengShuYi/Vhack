# CLAUDE.md

Rescue Swarm — autonomous drone swarm simulation for search-and-rescue. VHack 2026 submission.

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + FastMCP (Python) |
| Agent | LangChain + LangGraph + GPT-4o |
| Frontend | React + TypeScript + Three.js |

Entry points: `backend/server.py`, `agent/agent.py`, `frontend/src/App.tsx`

## Architecture

```
React Frontend  ──REST (poll /state 800ms)──  Backend (FastAPI :8000)
                ──POST /run-mission etc.──

Agent (LangGraph) ──MCP stdio──  Backend (FastMCP main thread)
```

### Backend (`backend/`)

Dual-server pattern in `server.py`:
- **FastMCP** on main thread (stdin/stdout) — serves MCP tools to the agent
- **FastAPI** in a background daemon thread — serves REST to frontend
- Both share `shared.sim` (`SimulationState` singleton from `shared.py`)
- **Never `print()` on main thread** — breaks MCP stdio connection. Use `sys.stderr`.

Simulation engine (`simulation.py`):
- 10×10 grid, terrain types: flat / forest / mountain / lake
- Lake and mountain cells are **impassable** (`hazard_cells[y][x] = True`)
- 4 zones: Z0 NW, Z1 NE, Z2 SW, Z3 SE (each 5×5)
- 5 ALPHA drones, spawned at random accessible positions
- `compute_path(x0,y0,x1,y1)` — BFS 8-directional routing around hazard cells; used for all movement (RTB, zone transit, voice dispatch)
- `assign_zone()` — generates zig-zag sweep path, skips impassable and already-scanned cells; gaps filled via `compute_path`
- `scan()` — Gaussian thermal bloom detection (threshold: `max_heat ≥ 78` AND `contrast ≥ 28`)
- `simulate_heartbeats()` — staggered drone discovery; drones come online at different ticks via `is_active` flag

Tick loop (Loop A, runs every 0.7s inside FastAPI event loop):
- Moves drones along `path_queue` or toward `target_x/y`
- Battery drain: 1% per cell (1.5% in forest), 25% per charge step at base
- Auto-RTB below 25% battery threshold
- Victim standby: drone holds when `is_waiting_response = True`
- Opportunistic scan of cells passed during transit

### Agent (`agent/agent.py`)

Two-phase loop (Loop B, separate process via MCP stdio):
1. **POLL** — calls `get_idle_drones()`, no LLM cost
2. **EXECUTE** — if idle drones exist:
   - `_is_trivial()`: skips LLM when every drone has exactly 1 option (no tradeoff) → rule-based assignment + logs `[AUTO]`
   - Otherwise: GPT-4o via LangGraph ReAct reasons and calls MCP tools
   - Fallback to `_rule_based_assignments()` if LLM unavailable or errors
   - Streams reasoning tokens to frontend via `POST /log`

`_rule_based_assignments()` — greedy parser: assigns first available zone per drone; RTBs any drone with no valid zone remaining.

Default sector strategy: ALPHA-1→Z0, ALPHA-2→Z1, ALPHA-3→Z2, ALPHA-4→Z3, ALPHA-5 support.

### MCP Tools (`backend/mcp_tools.py`)

| Tool | Purpose |
|------|---------|
| `list_drones()` | Active drone IDs |
| `get_status(drone_id)` | Battery, location, status |
| `get_grid_state()` | Available zones |
| `get_idle_drones()` | Priority-weighted assignment options menu |
| `assign_scan_zone(drone_id, zone_id)` | Claim zone + generate path queue |
| `return_to_base(drone_id)` | Force RTB via BFS path |

### REST Endpoints (`backend/server.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /state` | Full sim state (drones, zones, log, stats) |
| `POST /run-mission` | Activate simulation |
| `POST /stop-mission` | Halt mission |
| `POST /reset` | Reinitialize with new disaster layout |
| `POST /log` | Agent posts reasoning to mission log |
| `POST /victim-response` | Operator confirms rescue + AI triage |
| `POST /guide-victim` | Dispatch drone to escort mobile survivor to base |
| `POST /voice-command` | LLM parses voice command + reroutes nearest drone |

### LLM Gateway (`backend/llm_gateway.py`)

Auto-detects provider from env: `OPENAI_API_KEY` → GPT-4o, `GEMINI_API_KEY` → Gemini. Override with `ACTIVE_PROVIDER` and `LLM_MODEL`.

### Frontend (`frontend/src/`)

- `App.tsx` — main dashboard: polls `/state`, voice capture (Web Speech API), victim comms modal, mission-complete celebration overlay
- `Map3D.tsx` — Three.js 3D scene: drone models, terrain cells, base station, survivor markers
- `API_BASE` defaults to `http://127.0.0.1:8000`; override with `VITE_API_URL`

## Key Constants

- Grid: 10×10 | Zones: 5×5 each | Tick: 0.7s | Battery RTB threshold: 25%
- Requires `.env` at project root with `OPENAI_API_KEY`

## Known pitfalls

Before modifying the search/scan strategy, read
[docs/search-strategy-regressions.md](docs/search-strategy-regressions.md) —
post-mortem of changes that broke coverage of city/hazard zones and must not be
reintroduced (notably: opportunistic scan must stay restricted to the drone's
assigned zone, probability_map scale changes require coordinated downstream
retuning, and `get_status` must enrich zones with `score` / `terrain_counts`).

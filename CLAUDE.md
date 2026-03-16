# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VHack 2026 submission: an autonomous drone swarm simulation system for search-and-rescue scenarios. Three components communicate via standardized protocols:

- **Backend** (FastAPI + FastMCP): simulation engine + REST API + MCP tool server
- **Agent** (LangChain + LangGraph + GPT-4o): LLM-based drone orchestrator connecting via MCP
- **Frontend** (React + TypeScript + Three.js): real-time dashboard polling REST API every 800ms

## Running the System

Requires a `.env` file at the project root with `OPENAI_API_KEY=...` (and optionally `GEMINI_API_KEY=...` for victim triage and voice commands via llm_gateway).

**1. Install backend dependencies:**
```bash
pip install -r backend/requirements.txt
```

**2. Start the backend** (FastAPI on `http://127.0.0.1:8000` + FastMCP stdio):
```bash
cd backend && python server.py
```

**3. Start the agent** (separate process, connects to backend via MCP stdio):
```bash
cd agent && python agent.py ../backend/server.py
```

**4. Install and start the frontend:**
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at `http://localhost:5173`. API defaults to `http://127.0.0.1:8000`.

There is no test suite.

## Architecture

### Communication Flow
```
React Frontend  ←── REST (poll /state every 800ms) ──→  Backend (FastAPI port 8000)
                ←── POST /run-mission, /victim-response etc.

Agent (LangChain) ←── MCP stdio ──→  Backend (FastMCP main thread)
```

- **Agent → Backend:** MCP (Model Context Protocol) over stdio. Agent calls tools like `assign_scan_zone`, `get_idle_drones`.
- **Backend → Frontend:** REST endpoints; frontend polls `/state` at 800ms. Agent reasoning posted via `POST /log`.
- **Backend runs two servers**: FastMCP on main thread (for agent), FastAPI in a background thread (for frontend).

### Backend Dual-Server Pattern (`backend/server.py`)
- **FastMCP** runs on the main thread (`mcp.run()`), using stdin/stdout for the MCP protocol.
- **FastAPI** runs in a background daemon thread with its own asyncio event loop.
- Both share `shared.sim` (a `SimulationState` singleton from `backend/shared.py`).
- **CRITICAL**: Any `print()` in the main thread will break the MCP agent connection. All logging must go to `sys.stderr`.

### Simulation Engine (`backend/simulation.py`)
- 10×10 grid with terrain (flat/mountain/lake) and hazard cells
- 4 zones: Z0 (NW 0-4,0-4), Z1 (NE 5-9,0-4), Z2 (SW 0-4,5-9), Z3 (SE 5-9,5-9)
- 5 ALPHA drones spawned at random accessible positions
- Survivors have triage priority, heat signatures, and `can_move` flag
- `scan()` uses Gaussian thermal bloom detection (threshold: max_heat ≥ 78 AND contrast ≥ 28)
- `assign_zone()` generates zig-zag path queue with diagonal transit to nearest zone corner

### Simulation Tick Loop (Loop A — in `server.py`)
Runs every 0.7s inside FastAPI's event loop. No AI logic — handles:
- Drone movement along `path_queue` or toward `target_x/y`
- Battery drain (1% per cell), auto-charging at base
- Victim standby (drone waits when `is_waiting_response = True`)
- Emergency RTB when battery drops below `LOW_BATTERY_THRESHOLD` (25%)
- Opportunistic thermal scans when passing unscanned cells

### Agent Loop (Loop B — `agent/agent.py`)
Two-phase loop, separate process connecting via MCP stdio:
1. **POLL**: Calls `get_idle_drones()` — no LLM cost
2. **EXECUTE**: If idle drones exist, GPT-4o via LangGraph ReAct agent reasons and calls `assign_scan_zone()` / `return_to_base()`
- Sector assignment strategy: ALPHA-1→Z0, ALPHA-2→Z1, ALPHA-3→Z2, ALPHA-4→Z3, ALPHA-5 support
- Falls back to rule-based greedy assignment if LLM unavailable
- Streams reasoning tokens to frontend via `POST /log`

### MCP Tools (exposed by backend to agent)
| Tool | Purpose |
|------|---------|
| `list_drones()` | Active drone IDs |
| `get_status(drone_id)` | Battery, location, status |
| `get_grid_state()` | Available zones |
| `get_idle_drones()` | Priority-weighted assignment options menu |
| `assign_scan_zone(drone_id, zone_id)` | Claim zone + generate path queue |
| `return_to_base(drone_id)` | Force drone to RTB |

### REST Endpoints (for React frontend)
| Endpoint | Purpose |
|----------|---------|
| `GET /state` | Full sim state (drones, zone, log, stats) |
| `POST /run-mission` | Activate simulation |
| `POST /stop-mission` | Halt mission |
| `POST /reset` | Reinitialize with new disaster layout |
| `POST /log` | Agent posts reasoning to mission log |
| `POST /victim-response` | Operator confirms rescue + AI triage via llm_gateway |
| `POST /guide-victim` | Command drone to guide mobile survivor to base |
| `POST /voice-command` | AI parses voice command + reroutes nearest drone |

### LLM Gateway (`backend/llm_gateway.py`)
Used by `/victim-response` and `/voice-command` for AI parsing. Auto-detects provider:
- If `OPENAI_API_KEY` set → uses GPT-4o
- If `GEMINI_API_KEY` set → uses Gemini via OpenAI-compatible API
- Override with `ACTIVE_PROVIDER=OPENAI|GEMINI` and `LLM_MODEL=...`

### Frontend (`frontend/src/`)
- **App.tsx**: Main dashboard, polls `GET /state`, handles voice capture (Web Speech API), victim comms modal
- **Map3D.tsx**: Three.js 3D scene with drone models, terrain cells, base station, survivor markers
- **API_BASE**: Defaults to `http://127.0.0.1:8000`, override with `VITE_API_URL` env var

## Key Constants
- Grid: 10×10, zones: 5×5 (Z0–Z3)
- Simulation tick: 0.7s, AI plan interval handled by agent
- Battery: 1% per move, 25% per charge step, recall threshold 25%
- Backend port: 8000
- Frontend dev server: 5173 (Vite default)

# 🚁 RescueSwarm — AI Drone Search & Rescue Simulation

> **VHack 2026 — Case Study 3: First Responder of the Future: Decentralised Swarm Intelligence**

A decentralised swarm intelligence simulation where **SENTINEL**, a multi-agent AI system, autonomously orchestrates a fleet of 5 drones to perform search-and-rescue operations across a dynamically generated disaster zone. Agent-to-backend communication runs over the **Model Context Protocol (MCP)**; operator commands go over REST + WebSocket.

---

## 🔗 Important Links
- 📄 **RescueSwarm Documentation** — [View Documentation](https://www.notion.so/RESCUESWARM-Autonomous-Drone-Swarm-System-Documentation-3282193af50f81ada411d46badc34219)
- 🧠 **Agent Architecture Deep-Dive** — [Commander-Pilot System](https://www.notion.so/34b2193af50f81048ea2f2b727a28e14)
- 🔍 **Search Strategy Deep-Dive** — [How the Swarm Finds Survivors](https://www.notion.so/34b2193af50f8171b667d52d3756ae95)
- 🎤 **Pitch Deck** — [View Slides](https://drive.google.com/file/d/1IqTV977WO_vjv9dZSNyB_HCpZbG-59E2/view?usp=sharing)
---

## 👥 Team Members
- 👨‍💻 **Dennis** — 3rd Year @ UM
- 👨‍💻 **Shao Xian** — 3rd Year @ UM
- 👨‍💻 **Zhen Yu** — 3rd Year @ UM
- 👨‍💻 **Sean Sean** — 3rd Year @ UM

---

## 📋 Table of Contents

- [Project Overview](#-project-overview)
- [System Architecture](#-system-architecture)
- [Multi-Agent Design](#-multi-agent-design)
- [Features](#-features)
- [Project Structure](#-project-structure)
- [Tech Stack](#-tech-stack)
- [Setup & Installation](#-setup--installation)
- [How to Run](#-how-to-run)
- [Using the Dashboard](#-using-the-dashboard)
- [REST API Reference](#-rest-api-reference)
- [MCP Tools Reference](#-mcp-tools-reference)
- [Troubleshooting](#-troubleshooting)

---

## 🌐 Project Overview

RescueSwarm simulates a post-disaster rescue scenario where an operator deploys an autonomous AI-commanded drone swarm over a **20×15 grid** representing a collapsed urban zone. The system demonstrates:

- **Hierarchical multi-agent coordination** — a strategic **Commander** + five tactical **Pilots** exchange state through a lock-protected **Blackboard**.
- **Terrain-aware probabilistic search** — cell-level survivor probabilities (hazard > city > forest > flat) drive zone priorities, which drive per-drone menus.
- **Graceful degradation** — every LLM call has a deterministic `WeightedPlanner` fallback; the mission completes even with no API key.
- **Self-monitoring** — a `ContractChecker` audits coverage pace, high-score zones, and unaddressed leads every tick and triggers Commander re-planning on drift.
- **Human-in-the-loop** — radio text input, voice dispatch, AI triage on rescue confirmation, and mid-mission survivor escort.
- **Cross-mission learning** — a JSONL session log is summarised into `HISTORICAL INTEL` that primes the Commander on the next mission start.

The entire system runs locally — no physical hardware is needed.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         React Frontend                              │
│         (Vite + Three.js 3D Dashboard — localhost:5173)             │
│   Polls GET /state every 800ms │ WebSocket /ws/stream (live AI log) │
└────────────────────────┬────────────────────────────────────────────┘
                         │ REST API (HTTP)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│          Backend: FastAPI (port 8000) + FastMCP (stdio)             │
│  ┌────────────────────────┐   ┌────────────────────────────────┐   │
│  │  Simulation Tick Loop  │   │       REST Endpoints           │   │
│  │  (runs every 0.7s)     │   │  /state  /run-mission  /reset  │   │
│  │  - Drone movement      │   │  /brain/*  /radio-intel        │   │
│  │  - Battery drain       │   │  /voice-command /import-map    │   │
│  │  - Thermal scanning    │   │  /log /log/stream /timeline    │   │
│  │  - Probability boost   │   └────────────────────────────────┘   │
│  └────────────────────────┘                                        │
└────────────────────────┬────────────────────────────────────────────┘
                         │ MCP stdio
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                SENTINEL Agent Orchestrator                          │
│              (agent/agent.py — one Python process)                  │
│                                                                     │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐      │
│   │  Orchestrator│──▶│  Commander   │──▶│     Blackboard     │      │
│   │ (poll 0.5s)  │   │  strategic   │   │  priority_map,     │      │
│   │ fires events │   │  LLM         │   │  posture,          │      │
│   │ + idle signals│  └──────────────┘   │  urgent_redirect,  │      │
│   │              │                      │  zone_claims, lock │      │
│   │              │   ┌──────────────┐   │                    │      │
│   │              │──▶│  Pilot ×5    │◀──│                    │      │
│   │              │   │ tactical LLM │   └────────────────────┘      │
│   └──────────────┘   └──────────────┘                               │
│                                                                     │
│   Helpers: MissionMemory · ToolHooks · ContractChecker ·            │
│            SessionLog · WeightedPlanner                             │
└─────────────────────────────────────────────────────────────────────┘
```

The backend runs two servers simultaneously:
- **FastMCP** on the main thread (stdio) — serves MCP tools to the agent
- **FastAPI** on a background daemon thread (port 8000) — serves the React frontend

Both share a single `SimulationState` singleton via `backend/shared.py`.

---

## 🧠 Multi-Agent Design

SENTINEL is **not** a single LLM loop. It's three roles coordinated through a shared Blackboard:

| Role | Runs on | Wakes when | Output |
|---|---|---|---|
| **Orchestrator** | `asyncio` poll loop (0.5 s) | Always ticking | Fires events to Commander, idle signals to Pilots |
| **Commander** | One `asyncio` task | `mission_start`, `lead_grounded`, `survivor_found`, `battery_crisis`, `contract`, or 30 s safety timer | Writes `priority_map`, `posture`, `urgent_redirect` to Blackboard |
| **Pilot (×5)** | Five `asyncio` tasks (one per drone) | Drone becomes idle | Claims a zone atomically, calls `assign_scan_zone` via MCP |

**Four key design choices for the pitch:**

1. **Hierarchical context isolation** — Pilots see only their own drone's top-6 battery-affordable zones (~100 input tokens each), not the whole map.
2. **Blackboard pattern** — agents never message each other directly; they read/write shared state. Any one agent can fail and the rest keep working.
3. **Event-driven with safety net** — Commander runs only when the world changes; Pilots wake only on idle. 30 s timer prevents silence.
4. **Graceful degradation** — BRAIN mode toggle (`AUTO` / `CLOUD` / `EDGE` / `RULES`) lets the operator force the deterministic `WeightedPlanner` path in demos or when offline.

Full deep-dive: **[Commander-Pilot Architecture doc](https://www.notion.so/34b2193af50f81048ea2f2b727a28e14)**.

---

## ✨ Features

### 🤖 SENTINEL Multi-Agent Orchestrator
| Feature | Description |
|---|---|
| **Commander-Pilot split** | One strategic LLM + five tactical LLMs, coordinated via Blackboard. |
| **Posture system** | Commander picks `SPREAD / CONVERGE / LEAD_CHASE / RTB_CAUTIOUS` every wake — Pilots bias their choices accordingly. |
| **Atomic zone claims** | `asyncio.Lock`-protected `zone_claims` dict prevents two Pilots from ever picking the same zone. 60-tick TTL auto-clears stale claims. |
| **WeightedPlanner fallback** | `utility×2.2 + zone_score×5.0 + (1/√transit)×1.2 + LEAD-NEARBY×2.0 + FIND-NEARBY×1.5 + tag bonuses`. Kicks in on LLM error OR in RULES mode. |
| **ContractChecker self-audit** | Every tick: coverage pace, high-score unassigned zones, unaddressed CRITICAL leads. Contract violations fire fresh Commander events. |
| **Tiered MissionMemory** | Tier-0 (survivors, critical leads, drone failures — never dropped), Tier-1 (reassigns, completions), Tier-2 (routine). Recap injected into every Commander prompt. |
| **Cross-mission learning** | `SessionLog` writes JSONL per tick. `load_insights()` reads the last 5 missions at next mission start → `HISTORICAL INTEL` block in the first Commander brief. |
| **BRAIN mode toggle** | UI pill: `AUTO` (LLM + fallback), `CLOUD` (OpenAI/Gemini), `EDGE` (local LLM), `RULES` (deterministic only). Active engine reported back to UI after each decision. |
| **Multi-provider LLM** | Auto-detects OpenAI or Gemini from `.env`. Override with `ACTIVE_PROVIDER` + `LLM_MODEL`. |

### 🗺️ Disaster Simulation
| Feature | Description |
|---|---|
| **20×15 Dynamic Grid** | Unique map each mission: flat, forest, city, **hazard** (damaged urban within city clusters), lake. |
| **12 Search Sectors** | Z0–Z11, 5×5 cells each. Scored by summing per-cell survivor probability over unscanned cells. |
| **Terrain-weighted probability map** | `hazard=7, city=5, forest=2, flat=1, lake=0` per cell, normalised to sum=1. Drives zone scores, Commander priorities, and Pilot menus. |
| **Adaptive feedback** | Survivor find boosts adjacent zones' unscanned cell probabilities ×1.5 → swarm converges on clusters. |
| **Terrain-tiered zig-zag paths** | Within a zone, cells are visited in descending terrain-weight order (hazard → city → forest → flat), so early aborts still cleared the highest-value cells. |
| **5 ALPHA Drones** | Fleet spawns at random accessible positions; joins the mesh in staggered intervals. |
| **BFS Pathfinding** | 8-directional movement around impassable lake cells. |
| **Residual path saving** | Recalled mid-mission drones save remaining scan cells; next drone resumes via `[PARTIAL-resume]` tag. |
| **Battery cost model** | 1.0 %/cell (1.5 % in forest), 25 %/step charging at base, RTB auto-triggered below 25 %. |
| **Map import** | Upload a real-world image → terrain grid generation via `map_import.py` (OpenCV classification). |

### 🔍 Victim & Rescue System
| Feature | Description |
|---|---|
| **Gaussian thermal scan** | 5×5 thermal matrix per drone; survivor detected when `max_heat ≥ 78°C AND contrast ≥ 28°`. |
| **9-condition triage** | Victims mapped to P1-CRITICAL / P2-URGENT / P3-STABLE. |
| **AI triage brief** | LLM generates a 1-sentence recommendation when operator confirms rescue. |
| **Mobile survivor guiding** | Drones can escort `MOBILE_HEALTHY` / `MINOR_INJURY` survivors to base. |
| **Coordinates → dispatch** | Operator mentions coordinates in the rescue modal → nearest drone auto-dispatched. |
| **Victim registry** | ID, location, confidence, rescue status, triage tier, timestamp. |

### 📻 Human-in-the-Loop Channels
| Feature | Description |
|---|---|
| **Radio Panel — text intel** | Operator types `"victim in the forest area"` → LLM parses + grounds to (x,y) → `GROUNDED` lead → Commander `LEAD_CHASE` posture. |
| **Voice commands** | Click 🎙️ → speak *"Send a drone to grid 15, 5"* → nearest drone rerouted (Chrome/Edge only). |
| **Victim Comms modal** | Survivor found → popup with report/condition; operator confirms rescue or flags another coordinate. |
| **Urgent redirect** | `board.urgent_redirect = (x, y, reason)` — first Pilot within 8 cells consumes it and calls `investigate_lead`. |

### 🎛️ Interactive Dashboard
| Feature | Description |
|---|---|
| **3D grid** | Three.js scene with terrain cells, drone models, scan trails, survivor markers, base station. |
| **2D overlay** | Flat toggleable grid with terrain legend (CITY / HAZARD / FOREST / LAKE / SCANNED / BASE / DRONE). |
| **Live reasoning stream** | SENTINEL's chain-of-thought streams token-by-token via WebSocket. |
| **Colour-coded sub-agent logs** | `[COMMANDER BRIEF]` indigo, `[PILOT-ALPHA-N]` amber, `[SMART-FALLBACK]` green, `[RADIO]` / `[VOICE]` purple. |
| **Mission history** | Past missions stored in Supabase; replay view scrubs through tick-by-tick state. |
| **BRAIN pill** | Operator toggles AUTO / CLOUD / EDGE / RULES live; active engine colour-coded on the pill. |
| **Reasoning Timeline** | Chronological Commander briefs + Pilot decisions with duration + brain tag. |
| **Metrics panel** | Coverage pace, avg planning latency, zones completed, battery avg. |

---

## 📁 Project Structure

```
Vhack/
├── backend/
│   ├── server.py              # FastAPI REST + FastMCP stdio dual-server entry
│   ├── simulation.py          # 20×15 grid, drones, terrain, thermal scan, probability map
│   ├── drone.py               # Drone Pydantic model
│   ├── mcp_tools.py           # All MCP tools exposed to the agent
│   ├── shared.py              # SimulationState singleton
│   ├── llm_gateway.py         # OpenAI / Gemini provider abstraction
│   ├── map_import.py          # Image-to-grid terrain importer (OpenCV)
│   ├── radio.py               # Radio/voice intel parser + grounder
│   ├── landmarks.py           # Grid landmark registry (for voice coords)
│   ├── history.py             # Mission history REST layer
│   ├── supabase_client.py     # Supabase adapter (mission flush / history)
│   ├── mission_flusher.py     # End-of-mission report flush
│   ├── tests/                 # Pytest suite for backend
│   └── requirements.txt
├── agent/
│   ├── agent.py               # Orchestrator + Commander + Pilot classes, Blackboard
│   ├── memory.py              # Tiered MissionMemory (tier 0/1/2 ring buffers)
│   ├── contracts.py           # ContractChecker self-monitoring
│   ├── hooks.py               # ToolHooks pre/post validators
│   ├── session_log.py         # JSONL tick logger + cross-mission insights
│   ├── fallback.py            # WeightedPlanner deterministic fallback
│   ├── tests/                 # Pytest suite for the agent
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx            # Dashboard: polling, voice, victim modal, logs
│   │   ├── main.tsx
│   │   ├── index.css
│   │   ├── App.css
│   │   └── components/
│   │       ├── Map3D.tsx              # Three.js 3D scene
│   │       ├── BrainPill.tsx          # BRAIN mode toggle (portal dropdown)
│   │       ├── RadioPanel.tsx         # Text + push-to-talk intel input
│   │       ├── ReasoningTimeline.tsx  # Chronological decision log
│   │       ├── MetricsPanel.tsx       # Coverage / latency / battery stats
│   │       ├── MissionHistory.tsx     # Past missions browser
│   │       ├── MissionDetail.tsx      # Per-mission report view
│   │       └── MissionReplay.tsx      # Tick-by-tick scrub
│   ├── index.html
│   ├── package.json
│   ├── eslint.config.js
│   └── vite.config.ts
├── docs/
│   ├── search-strategy-regressions.md # Post-mortem of breakage patterns
│   └── superpowers/                   # Plan + spec documents
├── mission_reports/           # JSONL per-mission logs (git-ignored)
├── .env                       # API keys (not committed)
├── .github/workflows/ci.yml   # GitHub Actions: backend + agent tests + frontend lint/build
├── CLAUDE.md                  # Claude Code project instructions
├── README.md
└── requirements.md            # Full functional requirements
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Agent AI** | LangChain, LangChain-OpenAI, GPT-4o / Gemini 2.0 Flash |
| **Agent Protocol** | Model Context Protocol (MCP) via stdio |
| **Backend Framework** | FastAPI + FastMCP (Python 3.11+) |
| **Backend Server** | Uvicorn (ASGI) |
| **Data Models** | Pydantic v2 |
| **Image Processing** | OpenCV (map import classification) |
| **Mission Storage** | Supabase (Postgres + Storage) — optional |
| **Frontend** | React 19 + TypeScript + Vite 7 |
| **3D Rendering** | Three.js via `@react-three/fiber` + `@react-three/drei` |
| **Animations** | Framer Motion |
| **Charts** | Recharts |
| **Icons** | Lucide React |
| **Real-time Comms** | WebSocket (`/ws/stream`) + REST polling (800 ms) |
| **Voice Input** | Web Speech API (Chrome / Edge) |
| **CI** | GitHub Actions — pytest (backend + agent) + ESLint + `tsc` + `vite build` |

---

## ⚙️ Setup & Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| Node.js + npm | 20+ | For the frontend |
| OpenAI API Key | — | Optional — enables Commander + Pilot LLM reasoning. Falls back to `WeightedPlanner` when absent. |
| Gemini API Key | — | Optional — alternative LLM provider. |
| Supabase URL + Key | — | Optional — enables mission history + replay. Mission continues fine without. |

> **Without API keys:** The system runs in `RULES` mode automatically — all navigation, scoring, and assignments work via `WeightedPlanner`. Only LLM narration, AI triage, and voice parsing are disabled.

---

### Step 1 — Clone the Repository

```bash
git clone https://github.com/DennisHengShuYi/RescueSwarm.git
cd RescueSwarm
```

---

### Step 2 — Create the `.env` File

Create a `.env` in the **project root**:

```env
# At least one LLM key is recommended for full AI features:
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...

# Optional overrides:
# ACTIVE_PROVIDER=OPENAI        # or GEMINI
# LLM_MODEL=gpt-4o-mini

# Optional — enables mission history:
# SUPABASE_URL=https://xxx.supabase.co
# SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...
```

---

### Step 3 — Install Python Dependencies

```bash
pip install -r backend/requirements.txt -r agent/requirements.txt
```

---

### Step 4 — Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

---

## 🚀 How to Run

You need **two terminals** running simultaneously.

### Terminal 1 — Start the Backend + Agent

```bash
python agent/agent.py backend/server.py
```

This single command starts:
- ✅ **FastAPI REST server** on `http://127.0.0.1:8000`
- ✅ **FastMCP stdio server** (for the agent)
- ✅ **SENTINEL multi-agent orchestrator** (Orchestrator + Commander + 5 Pilots)

> ⚠️ **Important:** Do NOT run `python backend/server.py` separately while using the agent — they will create separate simulation states that diverge.

---

### Terminal 2 — Start the Frontend

```bash
cd frontend
npm run dev
```

Open your browser at: **`http://localhost:5173`**

---

## 🖥️ Using the Dashboard

1. **Click "Deploy Swarm"** — activates SENTINEL planning. The Commander writes its first brief within 1 tick.
2. **Watch the Reasoning Log** — colour-coded by sub-agent:
   - **Indigo** `[COMMANDER BRIEF]` — strategic priority/posture updates
   - **Amber** `[PILOT-ALPHA-N]` — per-drone tactical decisions
   - **Green** `[SMART-FALLBACK]` — rule-based fallbacks
   - **Purple** `[RADIO]` / `[VOICE]` — human-in-the-loop inputs
3. **Toggle BRAIN mode** — the pill next to the timer cycles AUTO / CLOUD / EDGE / RULES.
4. **Radio Panel** — type free-form intel or push-to-talk. Parsed into a lead with coordinates; triggers `LEAD_CHASE` posture.
5. **Voice Commands** — click 🎙️, speak a target (*"Send a drone to grid 15, 5"*). Chrome/Edge required.
6. **Victim Comms** — survivor-found modal pops up with report, condition, and coordinates field. Optionally add more intel and confirm rescue.
7. **Import Map** — upload an image to generate a real-world-shaped grid (OpenCV-classified).
8. **Mission History** — once a mission ends (Supabase configured), it appears in the History panel. Open for replay.
9. **Mission Complete** — all survivors rescued; drones auto-RTB; celebration overlay.

---

## 📡 REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/state` | Full sim state (drones, zones+score+terrain_counts, log, stats, leads, timeline, brain) |
| `POST` | `/run-mission` | Activate the swarm |
| `POST` | `/stop-mission` | Halt mission; flush to Supabase if configured |
| `POST` | `/reset?num_victims=N` | Regenerate grid + drones |
| `POST` | `/import-map` | Upload image; generate terrain grid |
| `POST` | `/log?text=...&level=AI` | Agent posts reasoning to mission log |
| `POST` | `/log/stream?text=...` | Agent posts streaming token chunk |
| `POST` | `/timeline` | Agent posts structured decision event for Reasoning Timeline |
| `POST` | `/victim-response?drone_id=...` | Operator confirms rescue; AI triage runs in background |
| `POST` | `/guide-victim?drone_id=...` | Escort mobile survivor to base |
| `POST` | `/voice-command?message=...` | Parse voice/text command; dispatch nearest drone |
| `POST` | `/radio-intel?lang=...&text=...` | Field-responder intel; creates a `lead` |
| `GET` | `/brain/status` | Returns `{mode, active}` |
| `POST` | `/brain/mode?mode=X` | Operator sets mode (`AUTO / CLOUD / EDGE / RULES`) |
| `POST` | `/brain/active?name=X` | Agent reports engine actually used on last decision |
| `POST` | `/metrics/planning-latency?ms=N` | Agent reports per-decision latency |
| `GET` | `/export-mission` | Download current mission log JSONL |
| `GET` | `/missions/current/export` | Export current mission (Supabase-bound JSON) |
| `WS` | `/ws/stream` | Live token stream to frontend |

---

## 🔧 MCP Tools Reference

Exposed by `backend/mcp_tools.py`. Called by the Orchestrator, Commander, and Pilots over MCP stdio.

### Read-only (zero side effects)

| Tool | Purpose |
|---|---|
| `list_drones()` | Active drone IDs |
| `get_status(drone_id)` | Battery, position, status label, assigned zone |
| `get_grid_state()` | Available (UNSCANNED) zones with scores |
| `get_swarm_status()` | Fleet-wide summary (counts, avg battery, coverage) |
| `get_thermal_scan(drone_id)` | Last 5×5 thermal matrix |
| `get_idle_drones()` | Per-drone top-6 battery-affordable zone menu with tags (`[LEAD-NEARBY]` / `[FIND-NEARBY]` / `[GAP-ROW]` / `[PARTIAL-resume]`) |
| `get_mission_intel()` | High-level situational brief |
| `get_survivor_intel()` | Found/rescued registry + triage |
| `get_probability_map()` | Current per-cell survivor-probability snapshot |
| `get_pending_leads()` | Unconsumed radio/voice leads |

### Actions (state-changing)

| Tool | Purpose |
|---|---|
| `assign_scan_zone(drone_id, zone_id)` | Generate terrain-tiered zig-zag sweep path; mark zone IN_PROGRESS |
| `return_to_base(drone_id)` | Force RTB via BFS path |
| `split_scan_zone(drone_a_id, drone_b_id, zone_id)` | Two drones share a zone (top/bottom halves) |
| `reassign_drone(drone_id, zone_id)` | Cancel current work, save residual, move to new zone |
| `investigate_lead(drone_id, x, y, reason)` | Fly to a radio/voice lead coordinate; 3×3 box scan |
| `set_strategic_brief(posture, priority_zones, notes)` | Commander writes strategic intent (also reflected in Blackboard) |

---

## 🧪 Running Tests

```bash
# Backend + agent tests
python -m pytest backend/tests/ agent/tests/ -v

# Frontend type-check + lint + build
cd frontend
npm run lint
npm run build
```

CI runs all three on every push (`.github/workflows/ci.yml`).

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Frontend blank / 504 error | Run `npm install` in `frontend/`, then hard-refresh (`Ctrl+Shift+R`) |
| `Port 8000 already in use` | Kill: `netstat -ano \| findstr :8000` then `taskkill /F /PID <pid>` |
| Drones not moving | Ensure `python agent/agent.py backend/server.py` is running (not just backend alone) |
| No LLM reasoning | Add `OPENAI_API_KEY` or `GEMINI_API_KEY` to `.env` OR toggle BRAIN pill to something other than `RULES` |
| Voice commands not working | Chrome / Edge only (Web Speech API); grant mic permission |
| Commander shows equal priorities (9.0/0.0 pattern) | `/state` isn't enriched with `score` + `terrain_counts`. Regression — see `docs/search-strategy-regressions.md §3`. |
| BRAIN pill label doesn't flip on click | Backend / agent running stale code. Restart both Python processes; hard-refresh browser. |
| Agent fails to connect | Wait 2–3 s after Terminal 1 starts before clicking "Deploy Swarm" |
| Mission history empty | Supabase env vars missing; set `SUPABASE_URL` + `SUPABASE_KEY` in `.env` |

---

## 📜 Full Requirements

Full functional and non-functional requirements: [requirements.md](./requirements.md)

Design deep-dives:
- **[Rescue Swarm System Documentation]([https://www.notion.so/34b2193af50f81048ea2f2b727a28e14](https://www.notion.so/RESCUESWARM-Autonomous-Drone-Swarm-System-Documentation-3282193af50f81ada411d46badc34219))**
- **[Commander-Pilot Agent Architecture](https://www.notion.so/34b2193af50f81048ea2f2b727a28e14)**
- **[Search Strategy — How the Swarm Finds Survivors](https://www.notion.so/34b2193af50f8171b667d52d3756ae95)**
- **[Regression Post-mortem](./docs/search-strategy-regressions.md)**

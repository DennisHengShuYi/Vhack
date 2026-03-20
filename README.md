# 🚁 RescueSwarm — AI Drone Search & Rescue Simulation

> **VHack 2026 — Case Study 3: First Responder of the Future: Decentralised Swarm Intelligence**

A decentralised swarm intelligence simulation where **SENTINEL**, an LLM-based AI agent, autonomously orchestrates a fleet of 5 drones to perform search-and-rescue operations across a dynamically generated disaster zone. All agent-to-drone communication is handled through the **Model Context Protocol (MCP)**.

---

## 🔗 Important Links
- 🎥 **Video Pitch** — [Watch Here]([https://your-video-link.com](https://drive.google.com/file/d/1EoJiO5pVr7WkDu42abikjdooGh9g27nc))
- 📄 **RescueSwarm Documentation** — [View Documentation]([https://your-doc-link.com](https://www.notion.so/RESCUESWARM-Autonomous-Drone-Swarm-System-Documentation-3282193af50f81ada411d46badc34219))

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

RescueSwarm simulates a post-disaster rescue scenario where a human operator deploys an autonomous AI-commanded drone swarm over a 20×15 grid representing a collapsed urban zone. The system demonstrates:

- **Decentralised AI decision-making** via a LangChain/LangGraph ReAct agent (SENTINEL)
- **Real-time swarm coordination** through MCP tool calls
- **Human-in-the-loop** interaction for victim confirmation, voice commands, and triage decisions
- **Dynamic terrain generation** with city, forest, lake, and flat zones affecting drone strategy

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
│  │  - Drone movement      │   │  /victim-response  /voice-cmd  │   │
│  │  - Battery drain       │   │  /log  /log/stream             │   │
│  │  - Thermal scanning    │   └────────────────────────────────┘   │
│  │  - Auto-charging       │                                        │
│  └────────────────────────┘                                        │
└────────────────────────┬────────────────────────────────────────────┘
                         │ MCP stdio
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│              SENTINEL Agent (agent/agent.py)                        │
│         LangChain + LangGraph ReAct + GPT-4o / Gemini              │
│  Phase 1 POLL: get_idle_drones() — no LLM cost                     │
│  Phase 2 EXECUTE: LLM reasons and calls assign_scan_zone() / RTB   │
│  Fallback: Rule-based greedy planner if LLM is unavailable         │
└─────────────────────────────────────────────────────────────────────┘
```

The backend runs two servers simultaneously:
- **FastMCP** on the main thread (stdio) — serves MCP tools to the agent
- **FastAPI** on a background daemon thread (port 8000) — serves the React frontend

Both share a single `SimulationState` singleton via `backend/shared.py`.

---

## ✨ Features

### 🤖 SENTINEL AI Orchestrator
| Feature | Description |
|---|---|
| **Chain-of-Thought Reasoning** | SENTINEL logs its tradeoff analysis before every assignment (proximity vs. priority, battery math) |
| **Battery-Aware Planning** | Calculates transit + scan + return costs before assigning any sector |
| **Dynamic Terrain Prioritisation** | Zones with city terrain are HIGH priority; forest is MEDIUM; flat is LOW |
| **Zone Uniqueness Enforcement** | Blocks two drones from being assigned the same zone in a single planning pass |
| **Spatial Spread Logic** | Prevents drone clustering — prefers assigning drones to different grid rows |
| **Rule-Based Fallback** | If LLM is unavailable or times out, a greedy rule-based planner takes over instantly |
| **Multi-Model Support** | Works with **GPT-4o** (OpenAI) or **Gemini 2.0 Flash** — auto-detects from `.env` |
| **Mission Memory** | Carries forward key events (survivor finds, zone completions) between planning ticks |

### 🗺️ Disaster Simulation
| Feature | Description |
|---|---|
| **20×15 Dynamic Grid** | Every mission generates a unique map — city districts, forest patches, and lake hazards |
| **12 Search Sectors** | Grid split into zones (Z0–Z11), each 5×5 cells, scanned in zig-zag pattern |
| **5 ALPHA Drones** | Fleet spawns at random accessible positions; joins the mesh network in staggered intervals |
| **BFS Pathfinding** | Drones navigate around impassable lake cells using Breadth-First Search |
| **Residual Path Saving** | If a drone is recalled mid-mission, the remaining scan path is saved for the next drone |
| **Terrain Battery Cost** | Forest cells cost 1.5% battery per move; all others cost 1.0% |

### 🔍 Victim & Rescue System
| Feature | Description |
|---|---|
| **Thermal Sensor Simulation** | Each drone generates a 5×5 thermal matrix; survivors emit a Gaussian heat bloom |
| **CNN-style Detection** | Survivor confirmed when `max_heat ≥ 78°C` AND `heat contrast ≥ 28°` |
| **9-Condition Triage** | Victims have one of 9 conditions mapped to P1-CRITICAL / P2-URGENT / P3-STABLE |
| **AI Triage** | LLM provides a 1-sentence triage recommendation when an operator confirms a rescue |
| **Mobile Survivor Guiding** | Healthy survivors (`MOBILE_HEALTHY`, `MINOR_INJURY`) can be escorted to base by a drone |
| **Victim Intel Dispatch** | Operator can mention coordinates in rescue message → nearest drone is auto-dispatched |
| **Survivor Registry** | Tracks ID, location, confidence score, rescue status, and timestamp for every victim |

### 🎛️ Interactive Dashboard
| Feature | Description |
|---|---|
| **3D Grid Visualisation** | Three.js 3D scene showing terrain, drone models, scan trails, and survivor markers |
| **Live AI Reasoning Stream** | SENTINEL's chain-of-thought streams token-by-token to the Mission Log via WebSocket |
| **Real-time Telemetry** | Battery levels, positions, and status for all 5 drones; mission timer; rescue counter |
| **Voice Commands** | Click the microphone → speak (e.g. *"Send drone to 15, 5"*) → nearest drone is rerouted |
| **Victim Comms Popup** | When a survivor is found, a modal appears with their report and condition; operator confirms rescue |
| **Estimated Finish Time** | Dynamic ETA based on unscanned cells and active drone count |

---

## 📁 Project Structure

```
Vhack/
├── backend/
│   ├── server.py          # FastAPI REST + FastMCP stdio dual-server entry point
│   ├── simulation.py      # Core simulation: 20×15 grid, drones, terrain, thermal scanning
│   ├── drone.py           # Drone data model (Pydantic)
│   ├── mcp_tools.py       # All MCP tool definitions exposed to the agent
│   ├── shared.py          # Shared SimulationState singleton
│   ├── llm_gateway.py     # OpenAI / Gemini provider abstraction
│   └── requirements.txt
├── agent/
│   ├── agent.py           # SENTINEL — LangChain + LangGraph orchestrator
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx        # Main dashboard component (polling, voice, victim modal)
│   │   ├── main.tsx       # React entry point
│   │   ├── index.css      # Global styles
│   │   ├── App.css
│   │   └── components/
│   │       └── Map3D.tsx  # Three.js 3D grid scene
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── .env                   # API keys (not committed to git)
├── .gitignore
├── README.md
└── requirements.md        # Full functional requirements specification
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Agent AI** | LangChain, LangGraph (ReAct), GPT-4o / Gemini 2.0 Flash |
| **Agent Protocol** | Model Context Protocol (MCP) via `langchain-mcp-adapters` |
| **Backend Framework** | FastAPI + FastMCP (Python 3.12+) |
| **Backend Server** | Uvicorn (ASGI) |
| **Data Models** | Pydantic v2 |
| **Frontend** | React 19 + TypeScript + Vite |
| **3D Rendering** | Three.js via `@react-three/fiber` + `@react-three/drei` |
| **Animations** | Framer Motion |
| **Icons** | Lucide React |
| **Real-time Comms** | WebSocket (`/ws/stream`) + REST polling |
| **Voice Input** | Web Speech API (browser-native, Chrome/Edge only) |

---

## ⚙️ Setup & Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | |
| Node.js + npm | 18+ | For the frontend |
| OpenAI API Key | — | Optional — enables LLM reasoning; falls back to rule-based if absent |
| Gemini API Key | — | Optional — alternative LLM provider for SENTINEL + victim triage |

> **Without API keys:** The system runs in rule-based fallback mode. All drone navigation and mission logic work normally; only LLM reasoning narration, voice commands, and AI triage are disabled.

---

### Step 1 — Clone the Repository

```bash
git clone https://github.com/DennisHengShuYi/RescueSwarm.git
cd Vhack
```

---

### Step 2 — Create the `.env` File

Create a `.env` file in the **project root** (`Vhack/.env`):

```env
# At least one key is recommended for full AI features:
OPENAI_API_KEY=sk-...           # For SENTINEL agent (GPT-4o) + voice commands + triage
GEMINI_API_KEY=AIza...          # Alternative: Gemini 2.0 Flash

# Optional overrides:
# ACTIVE_PROVIDER=OPENAI        # or GEMINI — forces a specific provider
# LLM_MODEL=gpt-4o              # override the model name
```

---

### Step 3 — Install Python Dependencies

```bash
pip install -r backend/requirements.txt
pip install -r agent/requirements.txt
```

Or install both in one command:

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
- ✅ **SENTINEL AI Orchestrator**

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

Once the frontend is open:

1. **Click "Run Mission"** — deploys the swarm and activates SENTINEL planning.
2. **Watch the Mission Log** — SENTINEL's chain-of-thought reasoning streams in real time.
3. **Monitor drone status** — battery bars, positions, and status labels update every 800ms.
4. **Voice Commands** — click the 🎙️ microphone button and say a target location (e.g. *"Send a drone to grid position 15, 5"*). Chrome or Edge is required.
5. **Victim Comms** — when a survivor is found, a popup appears with their condition and report. Optionally type additional intel (e.g. coordinates of another victim) and click **"Confirm Rescue"**.
6. **Mission Complete** — SENTINEL announces completion; all drones return to base automatically.

---

## 📡 REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/state` | Full simulation state (drones, zones, log, stats) |
| `POST` | `/run-mission` | Activate the swarm |
| `POST` | `/stop-mission` | Halt the mission immediately |
| `POST` | `/reset?num_victims=N` | Reinitialise with a fresh disaster layout |
| `POST` | `/log?text=...&level=AI` | Agent posts reasoning to the mission log |
| `POST` | `/log/stream?text=...` | Agent posts live token chunk (WebSocket broadcast) |
| `POST` | `/victim-response?drone_id=...` | Operator confirms rescue; runs AI triage in background |
| `POST` | `/guide-victim?drone_id=...` | Command drone to escort mobile survivor to base |
| `POST` | `/voice-command?message=...` | Parse voice/text command, dispatch nearest drone |
| `WS` | `/ws/stream` | WebSocket — live SENTINEL token stream to frontend |

---

## 🔧 MCP Tools Reference

These tools are exposed by `backend/mcp_tools.py` and called by the SENTINEL agent via MCP stdio.

| Tool | Parameters | Returns |
|---|---|---|
| `list_drones()` | — | Comma-separated list of active drone IDs |
| `get_status(drone_id)` | `drone_id: str` | Battery, location, status label |
| `get_idle_drones()` | — | Assignment options menu with battery estimates per drone |
| `assign_scan_zone(drone_id, zone_id)` | `drone_id, zone_id: str` | Generates zig-zag path queue; returns success message |
| `return_to_base(drone_id)` | `drone_id: str` | Forces drone onto BFS path home |
| `get_grid_state()` | — | Available (UNSCANNED) zones with priorities |

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Frontend blank / 504 error | Run `npm install` in `frontend/`, then hard-refresh (`Ctrl+Shift+R`) |
| `Port 8000 already in use` | Kill the process: `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F` |
| Drones not moving | Ensure `python agent/agent.py backend/server.py` is running (not just the backend alone) |
| No LLM reasoning in log | Add `OPENAI_API_KEY` or `GEMINI_API_KEY` to `.env` in the project root |
| Voice commands not working | Chrome or Edge required (Web Speech API); grant microphone permission in browser |
| Agent fails to connect | Wait 2–3 seconds after starting Terminal 1 before clicking "Run Mission" |

---

## 📜 Full Requirements

Full functional and non-functional requirements: [requirements.md](./requirements.md)

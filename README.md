# RescueSwarm — AI Drone Search & Rescue Simulation

A decentralized swarm intelligence simulation where an LLM-based agent (SENTINEL) orchestrates a fleet of autonomous drones to perform search-and-rescue operations in a disaster zone.

## 🏗️ Architecture

The project consists of three main components:
1. **Backend (`/backend`)**: A FastAPI + FastMCP server that manages the 2D simulation state, drone physics, and battery logic.
2. **Agent (`/agent`)**: The AI Orchestrator (SENTINEL) that uses LangChain and Model Context Protocol (MCP) to discover and command drones.
3. **Frontend (`/frontend`)**: A React + Vite dashboard with a 3D grid visualization to monitor the mission in real-time.

---

## 🚀 How to Run Manually

> **Requires three separate terminals.** The agent, backend, and frontend must all be running simultaneously.

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | |
| Node.js + npm | 18+ | For the frontend |
| OpenAI API Key | — | Optional: enables LLM reasoning; falls back to rule-based logic if absent |
| Gemini API Key | — | Optional: used for victim triage & voice commands |

---

### Step 1 — Clone & Set Up Environment

```bash
git clone <your-repo-url>
cd Vhack
```

Create a `.env` file in the **project root** (`Vhack/.env`):

```env
# At least one of the following is required for AI features:
OPENAI_API_KEY=sk-...        # For SENTINEL agent (GPT-4o) + LLM gateway
GEMINI_API_KEY=AIza...       # Alternative for LLM gateway (victim triage, voice)

# Optional overrides:
# ACTIVE_PROVIDER=OPENAI     # or GEMINI — forces a specific LLM provider
# LLM_MODEL=gpt-4o           # override the model name
```

> **Without API keys:** The system runs in rule-based fallback mode. All drone navigation and mission logic work; only LLM reasoning (mission log narration, voice commands, victim triage) is disabled.

---

### Step 2 — Install Python Dependencies

```bash
pip install -r backend/requirements.txt -r agent/requirements.txt
```

Or install them separately:

```bash
pip install -r backend/requirements.txt
pip install -r agent/requirements.txt
```

---

### Step 3 — Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

> **Troubleshooting:** If you see a Vite **504 Outdated Optimize Dep** error or a blank page, run:
> ```bash
> cd frontend
> npm install
> npm run dev
> ```
> Then **hard-refresh** your browser (`Ctrl+Shift+R` / `Cmd+Shift+R`) to clear the browser cache.

---

### Step 4 — Start the System

You only need **two terminals** if using the AI Agent.

Open **Terminal 1** — run the SENTINEL agent (this also starts the backend server automatically):

```bash
python agent/agent.py backend/server.py
```

This starts:
- **FastAPI REST server** on `http://127.0.0.1:8000` (for the dashboard)
- **FastMCP stdio server** (for the agent commands)
- **SENTINEL AI Orchestrator**

> **Important:** Do NOT run `python backend/server.py` in a separate terminal if you are using the agent, as they will create separate simulation states.

---

### Step 5 — Start the Frontend

Open **Terminal 3**:

```bash
cd frontend
npm run dev
```

Access the dashboard at: **`http://localhost:5173`**

---

### Step 6 — Use the Dashboard

1. Open `http://localhost:5173` in your browser.
2. Click **"Run Mission"** to deploy the swarm.
3. Watch SENTINEL's reasoning appear in the **Mission Log** panel.
4. Monitor drone battery levels — they auto-recharge when low.
5. Use **Voice Commands** (microphone button) to manually redirect drones.
6. When a victim is found, the UI shows a **Victim Comms** popup — respond and click "Confirm Rescue".

---

## 🗂️ Directory Structure

```
Vhack/
├── backend/
│   ├── server.py          # FastAPI REST + FastMCP stdio server
│   ├── simulation.py      # 10×10 grid, drones, zones, survivors
│   ├── drone.py           # Drone data model
│   ├── shared.py          # Shared SimulationState singleton
│   ├── llm_gateway.py     # OpenAI/Gemini LLM provider abstraction
│   └── requirements.txt
├── agent/
│   ├── agent.py           # SENTINEL LangChain + LangGraph orchestrator
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx        # Main dashboard component
│   │   └── components/    # Map3D, etc.
│   ├── package.json
│   └── vite.config.ts
├── .env                   # API keys (not committed)
├── .gitignore
├── CLAUDE.md              # Architecture notes for AI assistants
└── README.md
```

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Frontend shows blank page / 504 error | Run `npm install` in `frontend/`, then hard-refresh browser (`Ctrl+Shift+R`) |
| `Port 8000 already in use` | Kill the existing process: `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F` |
| Agent fails to connect | Make sure `python backend/server.py` is running first |
| No LLM reasoning in mission log | Add `OPENAI_API_KEY` or `GEMINI_API_KEY` to `.env` in project root |
| Voice commands not working | Chrome/Edge required (Web Speech API); allow microphone permission |

---

## 📜 Requirements

Full functional and non-functional requirements are documented in [requirements.md](./requirements.md).

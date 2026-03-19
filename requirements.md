# VHack 2026 — Case Study 3
#  RescueSwarm — AI Drone Search & Rescue Simulation
# Complete Project Requirements & Specification

---

## 1. System Overview

**RescueSwarm** is a fully software-simulated autonomous drone swarm system for search-and-rescue (SAR) operations. An LLM-based AI agent called **SENTINEL** orchestrates a fleet of 5 drones over a dynamically generated 20×15 disaster grid, using the **Model Context Protocol (MCP)** as the exclusive channel for all agent-to-drone commands.

The system is split into three independently running processes:

| Component | Technology | Role |
|---|---|---|
| **Backend** | FastAPI + FastMCP (Python) | Simulation engine, REST API, MCP tool server |
| **Agent** | LangChain + LangGraph + GPT-4o / Gemini | AI orchestrator — plans and dispatches drone assignments |
| **Frontend** | React + TypeScript + Three.js (Vite) | Real-time operator dashboard |

---

## 2. Grid & Environment

### 2.1 Grid Dimensions
- The disaster zone is a **20×15 grid** (300 cells total)
- Each cell has a **terrain type** and a **scanned state**

### 2.2 Terrain Types
| Terrain | Description | Survivor Probability | Passability | Battery Cost |
|---|---|---|---|---|
| `city` | Urban district — collapsed structures | Highest (weight ×5) | Passable | 1.0% / cell |
| `forest` | Woodlands — hikers, campers | Moderate (weight ×2) | Passable | **1.5% / cell** |
| `flat` | Open ground | Low (weight ×1) | Passable | 1.0% / cell |
| `lake` | Water body | Zero (weight 0) | **IMPASSABLE** | N/A |

### 2.3 Terrain Generation Algorithm
Every mission generates a unique map:
1. **City** — one large L-shaped or T-shaped urban district (core block 8–12 × 5–8 cells + arm extension of 10–25 additional cells)
2. **Forest** — 1–2 BFS-grown woodland patches, each 25–35 cells
3. **Lake** — one BFS-grown water body, 10–18 cells; all lake cells are automatically marked as hazard cells
4. **Base station** at `(0, 0)` is always kept `flat` and accessible

### 2.4 Search Zones
The grid is divided into **12 pre-defined search zones** (4 columns × 3 rows, each 5×5 cells):

| Zone | Bounds (sx,sy)→(ex,ey) | Row |
|---|---|---|
| Z0 | (0,0)→(4,4) | Row 0 (North) |
| Z1 | (5,0)→(9,4) | Row 0 |
| Z2 | (10,0)→(14,4) | Row 0 |
| Z3 | (15,0)→(19,4) | Row 0 |
| Z4 | (0,5)→(4,9) | Row 1 (Mid) |
| Z5 | (5,5)→(9,9) | Row 1 |
| Z6 | (10,5)→(14,9) | Row 1 |
| Z7 | (15,5)→(19,9) | Row 1 |
| Z8 | (0,10)→(4,14) | Row 2 (South) |
| Z9 | (5,10)→(9,14) | Row 2 |
| Z10 | (10,10)→(14,14) | Row 2 |
| Z11 | (15,10)→(19,14) | Row 2 |

Zone priority is computed dynamically from city cell count within each zone:
- `≥ 4` city cells → **HIGH**
- `≥ 1` city cell → **MEDIUM**
- `0` city cells → **LOW**

### 2.5 Cell States
| State | Description |
|---|---|
| Unscanned | Not yet visited by any drone |
| Scanned | Drone has performed a thermal scan on this cell |
| Hazard | Lake or inaccessible cell — drones cannot enter |

---

## 3. Drone Fleet

### 3.1 Fleet Configuration
- Fleet size: **5 drones** (ALPHA-1 through ALPHA-5)
- All drones spawn at **random accessible positions** (not all at base) on mission start
- Drones join the swarm mesh network in **staggered intervals** to simulate real-world boot sequences: ticks 0, 4, 7, 10, 13

### 3.2 Drone Data Model
| Field | Type | Description |
|---|---|---|
| `id` | str | Unique identifier (e.g. `ALPHA-1`) |
| `x`, `y` | int | Current grid coordinates |
| `base_x`, `base_y` | int | Base station coordinates (always `0, 0`) |
| `battery` | float | Battery percentage (0.0–100.0%) |
| `status` | str | `IDLE` / `ON_MISSION` / `RETURNING` / `CHARGING` / `OFFLINE` |
| `status_label` | str | Human-readable status (e.g. `SCANNING Z5`, `RTB`, `VICTIM STANDBY`) |
| `is_active` | bool | False until drone connects via heartbeat protocol |
| `is_charging` | bool | True while recharging at base |
| `is_waiting_response` | bool | True when drone is on victim standby awaiting operator input |
| `returning_to_base` | bool | True when drone is executing RTB |
| `assigned_zone_id` | str | Zone currently being scanned (or `None`) |
| `pending_zone_id` | str | Residual zone reserved for after current mission |
| `path_queue` | List[int,int] | Ordered sequence of grid cells to visit |
| `path_history` | List[int,int] | Last 12 visited cells (for trail visualisation) |
| `last_thermal_matrix` | List[List[int]] | 5×5 raw thermal sensor output from last scan |
| `last_thermal_scan` | Dict | Parsed scan result: confidence, triage, report |
| `voice_override` | bool | True when drone is on a voice/intel-commanded mission |
| `is_guiding` | bool | True when escort-guiding a mobile survivor to base |
| `join_tick` | int | Simulation tick when this drone comes online |
| `charge_cycles` | int | Number of completed recharge cycles |
| `scanned_grids` | int | Cells scanned in current zone assignment |

### 3.3 Movement Physics
- Movement is **8-directional** (including diagonals)
- Distance uses **Chebyshev metric**: `max(|Δx|, |Δy|)`
- Battery cost: **1.0% per cell** on flat/city terrain; **1.5% per cell** on forest terrain
- Thermal scan cost: **1.0% per scan**
- Recharge rate: **34% per charge step** (drone reaches 100% in ~3 charge steps)
- Recall threshold: **25% battery** (drone initiates automatic RTB)
- Emergency reserve: **8% minimum buffer** above return cost before assignment is allowed

### 3.4 Battery Safety System
Before every move, the simulation checks:
```
minimum_battery_to_return = (distance_to_base × drain_rate) + 8% reserve
safe_to_move = current_battery > minimum_battery_to_return
```
If `safe_to_move` is false, the drone **immediately aborts its current mission** and initiates RTB via BFS path home. The minimum return threshold is **dynamic** — it increases the further the drone is from base.

**Transit protection**: While a drone is travelling to (but has not yet entered) its assigned zone, the minimum return threshold is calculated using the zone's *farthest corner* from base, not the drone's actual current distance. This prevents false RTB triggers during transit.

### 3.5 Pathfinding
Drones use **BFS (Breadth-First Search)** for all navigation that requires avoiding hazard cells:
- Return to base
- Transit to zone entry corner
- Voice/intel command dispatch
- Residual zone resumption

For direct cell-by-cell movement within a zone, diagonal step movement is used with axis-only fallback if a diagonal step lands on a lake cell.

---

## 4. SENTINEL AI Agent

### 4.1 Architecture
SENTINEL is a **LangGraph ReAct agent** powered by either **GPT-4o** (OpenAI) or **Gemini 2.0 Flash** (Google). It runs as a separate process, communicating with the backend exclusively through MCP stdio.

**Two-phase mission loop:**
- **Phase 1 — POLL** (no LLM): Calls `get_idle_drones()` every tick. If no idle drones, sleeps 0.5s and repeats. Zero LLM cost.
- **Phase 2 — EXECUTE** (LLM or rule-based): If idle drones exist, invokes the ReAct agent to reason and call assignment tools.

### 4.2 SENTINEL System Prompt (Chain-of-Thought Mandate)
For every planning tick, SENTINEL must output a structured analysis block **before** calling any tools:

```
DRONE [id] @ (x,y) | Battery: B%
  TRADEOFF: [1 sentence comparing the top 2 zone options — proximity vs. priority]
  DECISION → [zone_id]: [reason in ≤15 words]
```

After all drone analysis blocks, one mission-level note:
```
MISSION PULSE: [1 sentence on overall coverage progress or urgent zone attention]
```

### 4.3 Strategic Assignment Rules
| Rule | Detail |
|---|---|
| **Priority First** | HIGH-priority (city) zones must be assigned before MEDIUM/LOW unless transit difference exceeds 12 cells |
| **Zone Uniqueness** | No two drones in the same planning batch may be assigned the same zone |
| **Spatial Spread** | Drones spread across different grid rows (Row 0: Z0-Z3, Row 1: Z4-Z7, Row 2: Z8-Z11); no two adjacent zones assigned in same batch |
| **Gap-Row Preference** | Within the same priority tier, prefer zones in rows with no active drone (GAP-ROW) |
| **Partial Zone Resume** | Prefer zones with saved residual paths — they complete faster |
| **No Idle Drones** | Every idle drone must receive an assignment or RTB command |
| **Mission Start Briefing** | On first tick, SENTINEL writes a full Mission Plan (HIGH→MEDIUM→LOW zone mapping, initial drone-to-zone assignments) before calling any tools |

### 4.4 Battery-Aware Pre-Assignment Validation
Before calling `assign_scan_zone()`, the agent (and the tool itself) validates:
```
transit_cost   = chebyshev(drone_pos, nearest_zone_corner)
scan_cost      = Σ(1.5 for forest cells + 1.0 for others) over unscanned cells
return_cost    = chebyshev(zone_farthest_corner, base)
total_needed   = transit_cost + scan_cost + return_cost + 8% reserve
assignment_ok  = drone.battery >= total_needed
```
If `assignment_ok` is false, the drone is sent to `return_to_base()`.

### 4.5 Dynamic Reallocation (Residual Path Saving)
When a drone is recalled mid-mission (low battery or manual RTB):
1. The remaining `path_queue` is saved as `zone.residual_path`
2. The zone status reverts to `UNSCANNED`
3. The nearest available drone is marked with `pending_zone_id` to cover the residual after finishing its current job
4. When that drone becomes idle, it automatically claims and inherits the saved partial scan path

### 4.6 Rule-Based Fallback Planner
If the LLM is unavailable, times out, or produces no tool calls, the system switches to a deterministic greedy planner:
- Parses the `get_idle_drones()` options menu with regex
- Assigns each drone to its highest-ranked valid option (Opt 1)
- Ensures no two drones are assigned the same zone (first-come-first-served)
- Any drone whose all options are already taken gets RTB

**Trivial tick optimisation**: If every idle drone has exactly one valid option with no tradeoff, the rule-based planner is used directly (skipping the LLM) to save API cost.

### 4.7 Mission Memory
SENTINEL maintains a rolling window of the last 8 key mission events (survivor detections, zone completions, battery RTBs) injected as context into each LLM planning call. This gives the agent awareness of recent events without feeding it the full mission log.

### 4.8 Live Token Streaming
SENTINEL uses `AsyncCallbackHandler` to stream LLM tokens to the frontend in real time:
- Every 15 tokens, the buffer is pushed to `POST /log/stream` → broadcast to WebSocket clients
- On LLM completion, the full reasoning block is posted to `POST /log` (permanent mission log)

### 4.9 Multi-Model Support
| Provider | Model | Config |
|---|---|---|
| OpenAI | `gpt-4o` (default) | Set `OPENAI_API_KEY` in `.env` |
| Google Gemini | `gemini-2.5-flash` (default) | Set `GEMINI_API_KEY` in `.env` |
| Override provider | Any | `ACTIVE_PROVIDER=OPENAI\|GEMINI` |
| Override model | Any | `LLM_MODEL=<model-name>` |

Auto-detection priority: if `OPENAI_API_KEY` is set, OpenAI is used. If only `GEMINI_API_KEY` is set, Gemini is used. If neither is set, rule-based fallback only.

---

## 5. MCP Tool Surface

All 12 MCP tools are registered in `backend/mcp_tools.py` and exposed via FastMCP stdio. The agent discovers them dynamically at startup — no hard-coded tool list.

### 5.1 Core Query Tools

| Tool | Signature | Returns |
|---|---|---|
| `list_drones()` | — | Comma-separated list of all active drone IDs |
| `get_status(drone_id)` | `drone_id: str` | Battery, position, status, zone, remaining path steps |
| `get_grid_state()` | — | All 12 zones: status, priority, assignment, scan % |
| `get_swarm_status()` | — | Fleet-level overview: active/idle/charging counts, avg battery, coverage % |
| `get_thermal_scan(drone_id)` | `drone_id: str` | Raw thermal matrix stats + CNN confidence result |

### 5.2 Planning Tools

| Tool | Signature | Returns |
|---|---|---|
| `get_idle_drones()` | — | Full Options Menu for all idle drones, sorted by priority then proximity |
| `get_mission_intel()` | — | Comprehensive situational brief: coverage %, incomplete zones, survivor status, current assignments |
| `get_survivor_intel()` | — | Known survivor positions, triage priorities, rescue status, guide eligibility |

**`get_idle_drones()` Options Menu format:**
```
[DRONE: ALPHA-N] Battery: B% @ (x,y)
  Opt 1: assign_scan_zone("ALPHA-N", "ZX") - Priority=HIGH, Transit=T, Cost=C, Risk=LOW/MED/HIGH, Terrain=[...], Scanned=P% [PARTIAL-resume] [GAP-ROW]
  Opt 2: assign_scan_zone("ALPHA-N", "ZY") - ...
  Opt 3: assign_scan_zone("ALPHA-N", "ZZ") - ...
```

Risk levels:
- **LOW**: `remaining_battery > 20%` after completing mission
- **MEDIUM**: `10% < remaining_battery ≤ 20%`
- **HIGH**: `remaining_battery ≤ 10%`

### 5.3 Action Tools

| Tool | Signature | Returns |
|---|---|---|
| `assign_scan_zone(drone_id, zone_id)` | `drone_id, zone_id: str` | Success message or error with reason |
| `return_to_base(drone_id)` | `drone_id: str` | Confirmation or error |
| `reassign_drone(drone_id, zone_id)` | `drone_id, zone_id: str` | Force-reassign an actively scanning drone to a new zone (emergency only) |
| `prioritize_zone(zone_id, priority)` | `zone_id: str, priority: HIGH\|MEDIUM\|LOW` | Updates zone priority dynamically |

**`assign_scan_zone()` validation chain (5 gates):**
1. Drone must exist and be active (connected via heartbeat)
2. Drone must not be on victim standby
3. Drone must not be charging below 90%
4. Zone must be `UNSCANNED` and not reserved
5. Drone battery must cover `transit + scan + return + 8% reserve`

If all gates pass, the zone is claimed and a zig-zag path queue is generated.

---

## 6. Simulation Engine

### 6.1 Simulation Tick Loop (Loop A)
Runs every **0.7 seconds** inside FastAPI's asyncio event loop. Handles all physical drone state changes — no AI logic.

**Per-tick operations (in order):**
1. Mission completion check — all 12 zones `COMPLETE` → recall swarm, stop mission
2. Increment tick counter, run heartbeat protocol (staggered drone activation)
3. For each active drone:
   - Skip if offline, victim standby
   - Auto-charge if at base and battery < 100%
   - Check for zone completion / residual handoff
   - Pop next cell from `path_queue` and execute move
   - Update guide victim position if drone is escorting
   - Apply terrain-dependent battery drain
   - Append position to `path_history` (max 12 entries)
   - Check `should_return_to_base()` → if true, abort zone, save residual, BFS home
   - Perform opportunistic thermal scan if cell is unscanned OR drone is in `voice_override` mode

### 6.2 Zig-Zag Zone Scan Pattern
When `assign_zone()` is called:
1. Find the nearest zone corner to the drone (Chebyshev distance)
2. BFS transit path to that corner (avoiding lake cells)
3. Generate zig-zag row-by-row sweep:
   - Starting direction determined by which corner was entered
   - Rows alternate left-to-right and right-to-left
   - Inaccessible cells are skipped; BFS bridge paths are inserted if gaps exceed 1 step
4. If a `residual_path` exists, resume from it instead (skipping already-scanned cells)

Path queue is assigned **atomically** (path first, zone ID second) to prevent the tick loop from falsely completing the zone on an empty queue.

### 6.3 Thermal Scanning System
Each `scan()` call generates a **5×5 thermal matrix** (simulated sensor array):
- Background ambient temperature: 20–38°C
- Hazard cells add 15–30°C across the matrix
- Survivors emit a **Gaussian heat bloom** centred on matrix position (2,2):
  ```
  heat[dy][dx] = survivor.heat_intensity × exp(-0.5 × √(dx² + dy²))
  ```
- Survivor heat intensity: 80–98°C

**CNN-style detection logic:**
```
max_heat = max(all matrix values)
heat_contrast = max_heat − mean(all matrix values)
detected = (max_heat >= 78) AND (heat_contrast >= 28)
confidence = min(99, int(max_heat))
```

**Thermal anomaly classification:**
- Confirmed human: `detected = True` AND survivor present at that cell
- Hot anomaly (non-human): `max_heat > 55°C` but detection thresholds not met
- Clear sector: `max_heat ≤ 55°C`

---

## 7. Victim & Survivor System

### 7.1 Survivor Placement
- Count: 10–15 survivors per mission (configurable via reset API; 1–50 range in UI)
- Placement is **terrain-weighted** — survivors are far more likely to be in city areas
- Lake cells cannot contain survivors

### 7.2 Victim Conditions & Triage
| Condition | Triage Priority | Can Move |
|---|---|---|
| `CRITICAL_INJURY` | P1-CRITICAL | No |
| `UNCONSCIOUS` | P1-CRITICAL | No |
| `CARDIAC_EVENT` | P1-CRITICAL | No |
| `MODERATE_INJURY` | P2-URGENT | No |
| `TRAPPED_STABLE` | P2-URGENT | No |
| `DEHYDRATION` | P2-URGENT | No |
| `SHOCK` | P2-URGENT | No |
| `MINOR_INJURY` | P3-STABLE | Random (50/50) |
| `MOBILE_HEALTHY` | P3-STABLE | **Always** |

Condition pool is weighted toward P1-CRITICAL conditions for realistic disaster simulation.

### 7.3 Victim States
| State | Trigger |
|---|---|
| `found = False` | Initial state |
| `found = True` | Drone thermal scan detects and confirms the survivor |
| `notified_rescue = True` | Rescue notification logged to mission log |
| `rescued = True` | Operator clicks "Confirm Rescue" OR guided survivor reaches base |

### 7.4 Victim Detection Flow
1. Drone arrives at a survivor's cell during its zone sweep
2. Thermal matrix is generated with the Gaussian heat bloom
3. CNN detection threshold is met → `survivor.found = True`
4. Drone enters `VICTIM STANDBY` (stops moving, `is_waiting_response = True`)
5. Frontend popup appears with victim report, condition, and triage priority
6. Operator optionally types a message (or uses voice) with their response

### 7.5 Rescue Actions
- **Confirm Rescue** → calls `POST /victim-response?drone_id=...&operator_message=...`
  - Drone is immediately freed (popup closes, drone resumes)
  - Background task runs AI triage analysis and coordinate extraction
- **Guide to Base** → calls `POST /guide-victim?drone_id=...`
  - Only available if `survivor.can_move = True`
  - Drone navigates to `(0,0)` with the survivor moving alongside
  - Survivor is rescued when drone reaches base

### 7.6 AI Victim Intel Parsing
When an operator includes text in their rescue confirmation message, an LLM (`llm_gateway`) extracts any grid coordinate references:
- Supports formats: `"X and Y"`, `"X,Y"`, `"(X,Y)"`, `"grid N"`, vague references
- If coordinates are found, the **nearest eligible drone** is dispatched to perform a 3×3 box scan around the target
- Runs concurrently with triage analysis in a background async task

### 7.7 Survivor Registry
Maintained in `DisasterZone.survivors` (list of dicts):
```python
{
  "id": "V001",
  "x": int, "y": int,
  "report": str,           # e.g. "Family of 4 trapped under rubble"
  "condition": str,        # e.g. "CRITICAL_INJURY"
  "triage_priority": str,  # "P1-CRITICAL" / "P2-URGENT" / "P3-STABLE"
  "heat_intensity": int,   # 80–98
  "found": bool,
  "rescued": bool,
  "can_move": bool,
  "notified_rescue": bool,
}
```

---

## 8. Voice Command System

### 8.1 Browser Voice Capture
- Uses the **Web Speech API** (Chrome / Edge required)
- Continuous mode with interim results — transcribed text is shown live as the operator speaks
- `recognition.lang = 'en-US'`

### 8.2 Voice Command Processing Pipeline
1. Operator clicks 🎙️ microphone button → browser captures speech → transcription shown
2. Transcription sent to `POST /voice-command?message=...`
3. Backend returns immediately (non-blocking)
4. Background async task calls `llm_gateway` to extract coordinates from the natural-language message
5. If coordinates found: nearest eligible drone is dispatched via `_dispatch_drone_to_target()`
6. Mission auto-activates if not already running

### 8.3 Drone Dispatch Logic (`_dispatch_drone_to_target`)
Drone selection uses a two-stage selection algorithm:

**Stage A — Proximity Rule** (if a source drone is identified):
- Source drone ≤7 cells from target AND battery >30% → use it directly

**Stage B — Global Nearest** (if proximity rule doesn't apply):
- All active drones with `battery > 35%`, not charging, not on victim standby
- Select closest by Chebyshev distance
- Logs full candidate comparison table to mission log

**After selection:**
- If drone has an active zone, releases it and saves the residual path
- Nearest available other drone is reserved to cover the residual
- Builds path: BFS transit to target + 3×3 clockwise box scan around target
- Sets `voice_override = True` — drone performs high-intensity scan on every step

---

## 9. Backend REST API

All endpoints served by FastAPI on `http://127.0.0.1:8000`.

| Method | Endpoint | Parameters | Description |
|---|---|---|---|
| `GET` | `/state` | — | Full simulation state: drones array, zone data, mission log, stats |
| `POST` | `/run-mission` | — | Activate mission; drones start moving |
| `POST` | `/stop-mission` | — | Halt mission immediately |
| `POST` | `/reset` | `num_victims: int = 10` | Regenerate disaster layout with new terrain and survivors |
| `POST` | `/log` | `text: str, level: str = "AI"` | Agent posts reasoning entry to mission log |
| `POST` | `/log/stream` | `text: str` | Agent posts live token chunk; broadcast to WebSocket clients |
| `POST` | `/victim-response` | `drone_id: str, operator_message: str` | Confirm rescue; run AI intel in background |
| `POST` | `/guide-victim` | `drone_id: str` | Command drone to escort mobile survivor to base |
| `POST` | `/voice-command` | `message: str` | Parse voice/text command; dispatch nearest drone |
| `WS` | `/ws/stream` | — | WebSocket — pushes live LLM token chunks to frontend |

### 9.1 `/state` Response Schema
```json
{
  "drones": [
    {
      "id": "ALPHA-1",
      "x": int, "y": int,
      "battery": float,
      "status": str,
      "status_label": str,
      "is_active": bool,
      "is_charging": bool,
      "is_waiting_response": bool,
      "returning_to_base": bool,
      "assigned_zone_id": str | null,
      "path_history": [[int, int], ...],
      "last_thermal_matrix": [[int, ...], ...] | null,
      "victim_report": str | null,
      "charge_cycles": int,
      "terrain": str
    }
  ],
  "zone": {
    "survivors": [...],
    "scanned_cells": [[bool, ...], ...],
    "hazard_cells": [[bool, ...], ...],
    "terrain_types": [[str, ...], ...],
    "zones": { "Z0": {...}, ... }
  },
  "log": [
    { "id": int, "ts": str, "level": str, "text": str, "drone": str | null }
  ],
  "stats": {
    "mission_active": bool,
    "total_victims": int,
    "victims_found": int,
    "victims_rescued": int,
    "coverage_pct": int,
    "elapsed_ts": str,
    "estimated_finish": str
  },
  "base_station": { "x": 0, "y": 0 },
  "streaming_text": str
}
```

### 9.2 Dual-Server Pattern
- **FastMCP** (main thread): runs `mcp.run()` listening on stdio for agent commands
- **FastAPI** (daemon thread): runs `uvicorn` on port 8000 for frontend REST/WebSocket
- Both share `shared.sim` (a `SimulationState` singleton from `backend/shared.py`)
- `print()` on the main thread is **forbidden** — it corrupts the MCP stdio protocol. All backend logging uses `sys.stderr`

---

## 10. Frontend Dashboard

### 10.1 Layout
Three-column layout with a fixed HUD header:
- **Left panel** — Fleet status OR Victims tab (switchable)
- **Center** — Mission map (2D grid or 3D view)
- **Right panel** — SENTINEL Reasoning Log

### 10.2 HUD Header
| Element | Description |
|---|---|
| Brand / Connection status | RESCUE SWARM logo + ONLINE/OFFLINE indicator |
| Coverage % | Scanned cells / total accessible cells |
| Found counter | Victims found / total |
| Rescued counter | Successfully extracted victims |
| Mission timer | Elapsed time in MM:SS format |
| Deploy/Stop button | Starts or halts the mission |
| Survivor count picker | Adjust 1–50 survivors before reset |
| Reset button | Regenerate map (disabled while mission active) |
| 3D toggle | Switch between 2D grid and Three.js 3D view |
| Info button | Simulation parameters modal |

### 10.3 Left Panel — Fleet Status
- One **drone card** per drone (ALPHA-1 to ALPHA-5)
- Shows: heartbeat dot (online/offline), drone ID, battery bar (colour-coded: green/amber/red), position, current terrain cell type, status label chip
- Offline drones show "AWAITING HEARTBEAT" state
- Drones on victim standby pulse with alert styling
- Filter toggle: ALL drones or RTB-only view
- Click any drone card to select it as active

### 10.4 Left Panel — Victims Tab
- Lists all **found** survivors sorted by: triage priority (P1 → P2 → P3), then rescued status
- Each entry shows: triage badge (colour-coded), victimID, grid coordinates, condition, and report text
- Click any entry to **pin-highlight** that victim's cell on the map (crosshair marker)
- Tab badge shows count of unrescued found survivors; turns urgent styling if > 0

### 10.5 Center Map — 2D Grid View
Each 20×15 cell renders:
- **Terrain colour**: city (grey-beige), forest (dark green), lake (steel blue), flat (dark base)
- **Scanned overlay**: teal-green tint + small tick mark
- **Drone marker**: CPU icon + drone number; pulsing/special styles for victim standby and RTB
- **Multi-drone stacking**: if 2+ drones share a cell, shows `×N` with all IDs
- **Survivor markers**: red pulsing dot (found, not yet rescued), green rescued cell, crosshair for highlighted/pinned victims
- **Base station**: power icon at (0,0)

### 10.6 Center Map — 3D View (Three.js)
The Map3D component renders a fully interactive 3D scene:
- 3D terrain blocks with height and colour per terrain type
- Drone 3D models floating above the grid with status-based animations
- Survivor markers in 3D space
- Orbit controls (pan, zoom, rotate)

### 10.7 Right Panel — SENTINEL Reasoning Log
- Streams SENTINEL's chain-of-thought in real time via WebSocket (`/ws/stream`)
- Structured log renderer parses and colour-codes log entries:
  - `DRONE [id] @ ...` headers
  - `TRADEOFF:` badges (gold)
  - `DECISION →` badges + zone chips (cyan)
  - `MISSION PULSE:` badges (purple)
  - System badges: `[AUTO]`, `[ROUTING]`, `[RTB]`, warnings (⚠️), completions (🏁)
- Log filter buttons: **AI** (default), **ALL**, **WARN**, **VICTIM**
- Auto-scrolls to latest; "↓ Latest" sticky button appears when user scrolls up

### 10.8 Victim Comms Modal
When a drone detects a survivor (`is_waiting_response = True`):
- Modal auto-opens; left panel switches to VICTIMS tab automatically
- Displays: victim report, condition, triage priority
- Voice capture: click 🎙️ → speak → transcription fills message box
- **Guide to Base** button (visible only if `can_move = True`)
- **Confirm Rescue** button → calls `/victim-response` with optional intel message

### 10.9 Mission Completion Celebration
When all survivors are rescued after a successful mission:
- Canvas-based **confetti particle animation** fires (160 particles, colour-coded in cyan/green/amber/white)
- Particles have gravity, rotation, and fade effects

### 10.10 Polling & WebSocket
- State polling: `GET /state` every **800ms** (REST)
- Live token streaming: WebSocket `/ws/stream` with **2-second auto-reconnect**
- WebSocket stream takes priority; REST `streaming_text` used as fallback

---

## 11. Non-Functional Requirements

| Requirement | Specification |
|---|---|
| **Simulation Only** | No physical hardware — fully Python + browser software simulation |
| **MCP Mandatory** | All agent-to-drone commands must go through MCP; hard-coded drone movement is prohibited |
| **Dynamic Fleet** | System must work with variable fleet sizes; supports 3–5 drones minimum |
| **No Hard-Coded Drone IDs** | Agent discovers drones at runtime via `list_drones()` MCP tool |
| **Chain-of-Thought Logging** | Every agent decision must be logged with reasoning before execution |
| **Graceful Fallback** | If LLM is unavailable, rule-based planner takes over automatically without operator intervention |
| **Responsiveness** | Victim comms frontend popup closes immediately after rescue confirmation; AI triage runs in background |
| **Port Isolation** | Backend on `8000`; frontend dev server on `5173`; MCP on stdio |
| **Cross-Origin** | CORS enabled for all origins (development mode) |
| **Python Version** | 3.12+ required (uses structural pattern matching, typing improvements) |
| **Node.js Version** | 18+ required for Vite and React 19 |

---

## 12. Expected Deliverables

| Deliverable | Description | Status |
|---|---|---|
| **SENTINEL Orchestrator** | Functional LangChain + LangGraph AI agent managing 5 simulated drones via MCP | ✅ Implemented |
| **FastMCP Server** | 12 MCP tools exposing all drone and simulation functions | ✅ Implemented |
| **Simulation Engine** | 20×15 disaster grid, 5 drones, terrain generation, thermal scanning, triage | ✅ Implemented |
| **REST API** | 9 FastAPI endpoints + WebSocket for the frontend | ✅ Implemented |
| **Mission Log** | Real-time structured chain-of-thought reasoning with WebSocket streaming | ✅ Implemented |
| **Interactive Dashboard** | React + Three.js operator dashboard with voice commands, victim comms, 3D map | ✅ Implemented |
| **Rule-Based Fallback** | Zero-LLM greedy assignment planner for API-less operation | ✅ Implemented |
| **Victim Triage AI** | LLM-powered triage analysis and coordinate extraction via `llm_gateway` | ✅ Implemented |

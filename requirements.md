# V Hack 2026 — Case Study 3
# First Responder of the Future: Decentralised Swarm Intelligence
## Functional Requirements

---

## 1. System Overview

A software simulation of an autonomous drone swarm commanded by an LLM-based agent to perform search-and-rescue operations in a disaster zone represented as a 2D grid. All agent-to-drone communication must use the **Model Context Protocol (MCP)**.

---

## 2. Grid & Environment

- The disaster zone is represented as a **20×20 grid**
- Each cell has one of the following states:
  - `UNSCANNED` — not yet visited
  - `CLEAR` — scanned, no survivor found
  - `SURVIVOR_DETECTED` — survivor found at this coordinate
  - `INACCESSIBLE` — blocked/unreachable zone
- Cells can be pre-assigned a **priority level**: `HIGH`, `MEDIUM`, or `LOW`
  - High priority: collapsed structures, coastlines, population centers
  - Low priority: already cleared, water bodies

---

## 3. Agent (Autonomous Command Agent)

### 3.1 Core Responsibilities
- Receive high-level mission goals via API input (e.g., *"Scan the south-east quadrant for survivors"*)
- Decompose goals into sequenced MCP tool calls
- Maintain a global map of scanned/unscanned cells
- Maintain a **Survivor Registry** (list of confirmed survivor coordinates)
- Demonstrate **Chain-of-Thought reasoning** — log reasoning before each action (e.g., *"Drone 2 has 45% battery, assigning nearest 4×4 sector to minimise transit cost"*)

### 3.2 Drone Discovery
- Must **not** hard-code drone IDs
- Must use MCP discovery mechanism to detect active drones on the network dynamically
- Must adapt mission plan based on the currently available fleet

### 3.3 Pre-Assignment Planning (Battery-Aware)
Before assigning a sector to any drone, the agent must:
1. Query the drone's current battery level and location
2. Calculate usable battery after accounting for transit and return costs:
   ```
   transit_cost   = manhattan(drone_pos, sector_start)
   return_cost    = manhattan(sector_furthest_cell, base_pos)
   usable_battery = current_battery - transit_cost - return_cost
   cells_coverable = usable_battery  # 1% per cell moved
   ```
3. Apply assignment rules:
   | Condition | Action |
   |---|---|
   | `cells_coverable > 0` | Assign nearest unscanned sector of that size |
   | `cells_coverable <= 0` | Send drone home immediately, no assignment |
4. Always select the **nearest unscanned sector** to minimise transit cost

### 3.4 Survivor Handling
- When a drone reports a survivor, the agent:
  1. Logs the coordinate and confidence score to the **Survivor Registry**
  2. Optionally dispatches a second drone to confirm the finding
  3. Allows the reporting drone to continue its current sector (no interruption)

### 3.5 Dynamic Reallocation
- When a drone is recalled mid-mission (low battery), the agent must:
  1. Record the **last scanned cell** of that drone
  2. Mark remaining cells in the sector as `UNSCANNED`
  3. Reassign those cells to the next available drone

### 3.6 Mission Loop
```
LOOP until all cells are CLEAR or SURVIVOR_DETECTED:
  1. Query all drones → get location, battery, status
  2. For each available drone:
     a. Calculate coverable cells from battery %
     b. Find nearest unscanned sector of that size (priority-first)
     c. Assign sector via MCP
  3. Drone executes sweep, reports per-cell results
  4. If survivor found → agent logs to Survivor Registry
  5. If battery < threshold mid-mission → drone returns home
  6. Agent reallocates uncovered cells to next available drone
END LOOP
```

---

## 4. MCP Client

- Acts as the communication bridge between the Agent and the MCP Server
- Translates agent tool call requests into MCP-compliant messages
- Returns MCP server responses back to the agent
- Must support **MCP tool discovery** (listing available drone tools dynamically)

---

## 5. MCP Server

- Hosts and exposes all drone functions as standardised MCP tools
- Manages routing of commands to the correct drone instance
- Returns drone responses to the MCP Client
- Must support dynamic registration of drones (no hard-coded drone list)

### 5.1 Exposed Drone Tools (MCP Tool Signatures)
| Tool | Parameters | Returns |
|---|---|---|
| `list_drones()` | — | List of active drone IDs |
| `get_status(drone_id)` | `drone_id: str` | `{ battery: int, location: (x,y), status: str }` |
| `move_to(drone_id, x, y)` | `drone_id: str, x: int, y: int` | `{ success: bool, location: (x,y), battery: int }` |
| `thermal_scan(drone_id)` | `drone_id: str` | `{ survivor_detected: bool, confidence: float, location: (x,y) }` |
| `return_to_base(drone_id)` | `drone_id: str` | `{ success: bool }` |
| `get_battery_status(drone_id)` | `drone_id: str` | `{ battery: int }` |

---

## 6. Drone (Simulated)

Each drone is a simulated software entity. No physical hardware is required.

### 6.1 State
- `drone_id` — unique identifier
- `location` — current `(x, y)` coordinate on the grid
- `battery` — integer percentage (0–100)
- `status` — one of: `IDLE`, `ON_MISSION`, `RETURNING`, `CHARGING`

### 6.2 Initial Positioning
- Drones start **distributed across different zones** of the grid, not all at base
- On mission start, the agent queries every drone's initial location before planning
- The agent factors in each drone's starting position when calculating transit cost to the first assigned sector

### 6.3 Functions
- Move to a target `(x, y)` coordinate (costs 1% battery per cell travelled)
- Perform a thermal scan at the current cell
- Report current battery status
- Report current location
- Return to base when battery is critically low or mission is complete
- Recharge at base (simulated, recharges to 100%)

### 6.4 Battery Rules
- Each cell movement costs **1% battery**
- Distance is calculated using **Manhattan distance**: `|x2-x1| + |y2-y1|`
- Before every move, the drone checks if it has enough battery to complete the move **and** return home:
  ```
  distance_to_base = manhattan(current_pos, base_pos)
  safe_to_move = current_battery - 1 > distance_to_base(next_pos, base_pos)
  ```
- If `safe_to_move` is false, the drone **immediately aborts its mission and returns home**
- The return-home threshold is **dynamic** — it increases the further the drone is from base
- Drone recharges to 100% upon reaching base

### 6.5 Agent Battery-Aware Assignment
When assigning a sector, the agent must account for:
1. **Transit cost** — battery needed to travel from current location to the sector
2. **Scan cost** — battery needed to sweep all cells in the sector (1% per cell)
3. **Return cost** — battery needed to return from the furthest cell in the sector to base

```
usable_battery = current_battery - transit_cost - return_cost
cells_coverable = usable_battery  # 1% per cell
```

If `cells_coverable <= 0`, the drone is sent home immediately without assignment.

---

## 7. Survivor Registry

A data structure maintained by the agent:
```
SurvivorRegistry = [
  { id, location: (x, y), confidence: float, confirmed_by: [drone_id], timestamp },
  ...
]
```

---

## 8. Non-Functional Requirements

- **Simulation Only** — no physical hardware required; use a Python-based environment or 2D grid
- **Mandatory MCP** — all agent-to-drone communication must go through MCP; hard-coding drone movements is prohibited
- **Chain-of-Thought Logging** — every agent decision must be logged with its reasoning before execution
- **Dynamic Fleet** — system must work with variable fleet sizes (minimum 3–5 drones for demonstration)
- **No Hard-Coded Drone IDs** — agent discovers drones at runtime via MCP

---

## 9. Expected Deliverables

| Deliverable | Description |
|---|---|
| **The Orchestrator** | Functional AI agent managing a simulated fleet of 3–5 drones |
| **MCP Server Implementation** | Code exposing all drone tools to the agent |
| **Mission Log** | Step-by-step agent reasoning trace and successful mission completion demo |

---


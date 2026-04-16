# Judge Feedback Improvements — Design Spec

**Date:** 2026-04-14
**Context:** Addressing preliminary round judge feedback for VHack 2026 finals (1-2 week timeline).
**Scope:** 2 features — Live Metrics Dashboard, Survivor Mobility Tracking.

---

## 1. Live Metrics Dashboard

### Problem
Both judges flagged the lack of quantitative performance metrics. The technical judge specifically called out: no coverage %, no mission completion time, no victim detection accuracy, no false positive rates, and hardcoded thresholds without validation. The business judge directly asked "how long can the drone fly before needing charging?"

### Design

#### 1.1 Backend — `MissionMetrics` dataclass (`simulation.py`)

Add a `MissionMetrics` class that accumulates stats as the simulation runs. Updated on every tick.

Fields:
- `mission_start_time: float` — set on mission start
- `mission_elapsed_seconds: float` — derived each tick
- `total_scannable_cells: int` — non-hazard cells, computed once on reset
- `total_cells_scanned: int` — incremented on each unique cell scan
- `coverage_percent: float` — `total_cells_scanned / total_scannable_cells * 100`
- `total_victims: int` — count of placed survivors
- `victims_found: int` — count of discovered survivors
- `victims_rescued: int` — count of confirmed rescues
- `detection_rate_percent: float` — `victims_found / total_victims * 100`
- `false_positives: int` — thermal bloom triggered but no victim present
- `true_positives: int` — thermal bloom triggered and victim found
- `thermal_threshold_config: dict` — `{"min_heat": 78, "min_contrast": 28}` — makes thresholds visible
- `cells_per_full_charge: float` — derived: `(100 - LOW_BATTERY_THRESHOLD) / BATTERY_DRAIN_MOVE`
- `per_drone_stats: Dict[str, DroneStats]` — per-drone breakdown

`DroneStats` fields:
- `cells_moved: int`
- `scans_performed: int`
- `battery_used: float` — total % drained across the mission
- `charges_count: int`
- `idle_ticks: int`
- `current_battery: float`

#### 1.2 Backend — Integration points

- **`GET /state`**: Add `metrics` key to the response dict containing the `MissionMetrics` serialized as dict. No new endpoint needed.
- **`simulation.py` tick loop**: Increment counters during `move_drones()`, `scan()`, and `charge_step()`.
- **`scan()` function**: Track `false_positives` and `true_positives` by comparing thermal bloom detection result against actual victim placement.
- **Reset**: Clear metrics on `POST /reset`. Initialize `total_scannable_cells` and `total_victims` from the new grid.

#### 1.3 Frontend — `MetricsPanel` component

New component rendered alongside the existing dashboard in `App.tsx`.

Layout:
- **Top bar**: Mission timer (elapsed), coverage % progress bar, victims found/total
- **Fleet overview**: Avg battery across fleet, `cells_per_full_charge` stat (answers the business judge's battery question)
- **Per-drone mini-cards**: Drone ID, battery %, cells scanned, status badge (SCANNING / CHARGING / RTB / IDLE)
- **Detection stats**: True positives, false positives, detection rate %. Show the thermal threshold values (`heat >= 78, contrast >= 28`) alongside their hit/miss counts — makes hardcoded thresholds transparent and demonstrates effectiveness
- **Mission summary** (shown on mission complete): Final coverage %, total time, victims found vs total, fleet efficiency

Data source: Existing `/state` poll (800ms interval) — the `metrics` field added above.

No new dependencies. Plain React + TypeScript, styled consistently with existing dashboard.

---

## 2. Survivor Mobility Tracking

### Problem
Business judge noted that survivors may be moving between scans, and implementing mobility tracking was listed in the roadmap but not yet implemented.

### Design

#### 2.1 Backend — Victim mobility model (`simulation.py`)

**Mobile conditions:** `MOBILE_HEALTHY` and `MINOR_INJURY` victims are flagged `is_mobile = True`. All other conditions are stationary.

**New victim fields** (added to victim dict in `SimulationState`):
- `is_mobile: bool` — derived from condition
- `last_seen_tick: Optional[int]` — tick when a drone last scanned this victim
- `position_history: List[dict]` — `[{"x": int, "y": int, "tick": int}, ...]`

**Movement logic** — new method `simulate_survivor_movement()`:
- Called every 5 ticks (~3.5 seconds of sim time)
- For each mobile victim that is NOT rescued:
  - 30% chance to move to a random adjacent non-hazard cell (8-directional)
  - Update victim's `x, y` coordinates
  - Append to `position_history`
  - Update heat map: zero out the Gaussian bloom at the old cell and regenerate a fresh bloom at the new cell (instant transfer, not gradual decay)
  - If victim was previously discovered (has `last_seen_tick`), mark old position as a **stale sighting**

**Stale sightings:**
- Maintained as a list on `SimulationState`: `stale_sightings: List[dict]`
- Each entry: `{"x": int, "y": int, "victim_id": str, "stale_since_tick": int}`
- Cleared when the victim is re-found or rescued
- Exposed in `/state` response for frontend rendering

**Scope guard:**
- Only undiscovered or discovered-but-unrescued victims move
- Once rescue confirmed via `POST /victim-response`, victim stops moving and is removed from mobile pool
- Movement is simple random-neighbor — no victim pathfinding
- Maximum movement radius: no cap (they drift naturally), but 30% chance per 5-tick window means ~1 cell every ~17 ticks on average

#### 2.2 MCP Tool Changes (`mcp_tools.py`)

- `get_idle_drones()` response gains a new assignment option type: `"RE-SCAN stale sighting at (x,y)"` for stale sightings older than 10 ticks
- This appears as a high-priority option in the menu, ranked above zone scanning for nearby drones (since re-finding a known survivor is more urgent than new area coverage)
- Agent prompt updated to understand re-scan assignments

#### 2.3 Frontend Changes (`Map3D.tsx` + `App.tsx`)

- **Mobile survivor marker**: Distinct visual — pulsing ring or different color from stationary survivors
- **Stale sighting marker**: "?" icon at last-known position, faded/ghosted appearance
- **Metrics panel additions**: `mobile_survivors: int`, `stale_sightings: int`, `re_scans_triggered: int`

---

## Files to Modify

| File | Changes |
|------|---------|
| `backend/simulation.py` | `MissionMetrics` class, metrics accumulation in tick loop, `simulate_survivor_movement()`, stale sightings, mobile victim fields |
| `backend/server.py` | Add `metrics` to `/state` response, call `simulate_survivor_movement()` in tick loop |
| `backend/mcp_tools.py` | Add re-scan option to `get_idle_drones()` |
| `backend/shared.py` | No changes expected (uses `SimulationState` from simulation.py) |
| `frontend/src/App.tsx` | Render `MetricsPanel`, pass metrics data, render stale sighting indicators |
| `frontend/src/components/MetricsPanel.tsx` | New component — metrics display |
| `frontend/src/components/Map3D.tsx` | Mobile survivor markers, stale sighting "?" markers |

## Files NOT Modified

- `backend/drone.py` — drone model unchanged
- `backend/llm_gateway.py` — no LLM changes
- `agent/agent.py` — agent already handles assignment options from `get_idle_drones()`; re-scan shows up as a new option type that the LLM or rule-based planner can pick

## Implementation Order

1. `MissionMetrics` class + accumulation logic in `simulation.py`
2. Wire metrics into `/state` response in `server.py`
3. `MetricsPanel` frontend component
4. Survivor mobility model in `simulation.py`
5. Stale sightings + re-scan option in `mcp_tools.py`
6. Mobile/stale markers in `Map3D.tsx`
7. Integration testing — run full mission, verify metrics accuracy and survivor movement

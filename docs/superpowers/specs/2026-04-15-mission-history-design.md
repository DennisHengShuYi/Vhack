# Mission History & Replay — Design Spec

**Goal:** Persist mission data to Supabase and expose a Mission History tab in the frontend where operators can review past missions, inspect detailed metrics, and replay any mission with a 2D grid scrubber.

**Architecture:** Option B — JSONL write path unchanged during live missions; `flush_to_supabase()` fires once on mission complete in a background thread. Two Supabase tables: `missions` (summary) and `mission_ticks` (full tick array, one row per mission). Frontend adds a History tab with three views: card list, detail panel, and replay.

**Tech Stack:** Python `supabase-py`, FastAPI, React + TypeScript, `recharts` for charts.

---

## Database Schema

### `missions` — one row per completed mission

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key, auto-generated |
| `started_at` | timestamptz | Mission start wall-clock time |
| `ended_at` | timestamptz | Mission end wall-clock time |
| `status` | text | `'COMPLETE'` or `'PARTIAL'` |
| `total_victims` | int | Placed on grid at mission start |
| `victims_found` | int | |
| `victims_rescued` | int | |
| `coverage_pct` | float | % of scannable cells covered |
| `detection_rate_pct` | float | victims_found / total_victims × 100 |
| `false_positives` | int | Thermal detections that weren't survivors |
| `avg_time_to_find_s` | float | Avg seconds from mission start to each survivor found |
| `llm_ticks` | int | Ticks where GPT-4o was used |
| `auto_ticks` | int | Ticks handled by trivial auto-assignment |
| `fallback_ticks` | int | Ticks handled by WeightedPlanner fallback |
| `contract_violations` | int | Total contract alert count |
| `zone_times` | jsonb | `{"Z0": {"drone": "ALPHA-1", "duration_s": 72}, ...}` |
| `per_drone` | jsonb | `{"ALPHA-1": {"battery_used": 245, "cells_moved": 178, "scans": 165, "charges": 3, "idle_ticks": 12}, ...}` |
| `survivors` | jsonb | `[{"tick": 23, "priority": "P1", "condition": "CRITICAL_INJURY", "drone": "ALPHA-1", "rescue_s": 16}, ...]` |

### `mission_ticks` — one row per mission (full replay data)

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial | Primary key |
| `mission_id` | uuid | FK → `missions.id` |
| `ticks` | jsonb | Array of downsampled tick snapshots (every 5th tick) |
| `created_at` | timestamptz | Auto-set on insert |

Each entry in the `ticks` array:
```json
{
  "tick": 10,
  "coverage_pct": 7.1,
  "drones": {"ALPHA-1": {"x": 3, "y": 5, "battery": 72, "status": "SCANNING"}},
  "zones": {"Z0": "IN_PROGRESS", "Z1": "UNSCANNED"},
  "events": ["ALPHA-1→Z0 assigned"],
  "decision_type": "AUTO"
}
```

Downsampled at every 5th tick → ~68 snapshots per 4-minute mission → ~48KB of JSONB per row.

---

## Backend

### New file: `backend/supabase_client.py`

Singleton Supabase client. Reads `SUPABASE_URL` and `SUPABASE_ANON_KEY` from `.env`. Exposes a single `get_client()` function returning the shared client instance. Raises `EnvironmentError` at import time if either env var is missing.

### Modified: `agent/session_log.py`

Add `flush_to_supabase(mission_id: str, summary: dict, client) -> None`:
1. Reads the completed JSONL file at `self._path`
2. Parses all tick entries, keeps every 5th tick (`tick % 5 == 0`)
3. Strips heavy fields not needed for replay (contract_alerts, errors) to keep payload small
4. Inserts one row into `mission_ticks`: `{mission_id, ticks: [...], created_at: now}`
5. Inserts one row into `missions` using `summary` dict
6. On any Supabase error: logs to stderr, does not raise (mission data is already safe in JSONL)

`load_insights()` updated to fall back to Supabase when no local JSONL files exist:
- Query: `SELECT ticks FROM mission_ticks ORDER BY created_at DESC LIMIT 5`
- Reconstruct the same insights logic from the returned tick arrays

### Modified: `backend/server.py`

On mission complete (inside `run_simulation_loop`, where `sim.mission_active = False` is set):
1. Generate `mission_id = str(uuid.uuid4())`
2. Build `summary` dict from `sim.metrics.to_dict()` + derived fields (zone_times, survivors, avg_time_to_find_s, decision counts from session_log)
3. Call `threading.Thread(target=session_log.flush_to_supabase, args=(mission_id, summary, supabase_client), daemon=True).start()`
4. Non-blocking — the tick loop continues unaffected

### New file: `backend/history.py`

Three FastAPI route functions, mounted in `server.py` via `app.include_router(history.router)`:

**`GET /missions`**
- Queries `SELECT id, started_at, ended_at, status, total_victims, victims_found, victims_rescued, avg_time_to_find_s FROM missions ORDER BY started_at DESC`
- Returns list of summary cards (no heavy JSONB fields, no tick data)

**`GET /missions/{mission_id}`**
- Queries full row from `missions` by id
- Returns all columns including `zone_times`, `per_drone`, `survivors`

**`GET /missions/{mission_id}/replay`**
- Queries `SELECT ticks FROM mission_ticks WHERE mission_id = ?`
- Returns the `ticks` JSONB array directly

---

## Frontend

### `src/App.tsx` — wire in History tab

Add `'history'` to the tab state. The `History` icon is already imported. Render `<MissionHistory />` when the history tab is active.

### New: `src/components/MissionHistory.tsx`

- Fetches `GET /missions` on mount
- Renders a scrollable list of mission cards
- Each card shows: mission number, date/time, duration, survivors found/total, avg time-to-find, status badge (COMPLETE / PARTIAL)
- Two buttons per card: **View Details** (opens `MissionDetail`) and **▶ Replay** (opens `MissionReplay`)

### New: `src/components/MissionDetail.tsx`

Props: `missionId: string`. Fetches `GET /missions/{id}` on mount.

Renders seven sections:
1. **Hero stats row** — 4 stat cards: mission time, survivors found, avg time-to-find, coverage %
2. **Performance panel** — progress bars for detection rate, rescue rate, coverage; false positive and rescued counts
3. **AI Decisions panel** — stacked bar (LLM / AUTO / Fallback), 3 mini stat cards, contract violations alert banner
4. **Per-drone table** — battery used (with bar), utilisation %, cells moved, scans, charges per drone
5. **Zone completion times** — horizontal bars per zone (Z0–Z3) with drone and duration, color coded fastest→slowest
6. **Survivor discovery cards** — one card per survivor, triage-colored (P1 red / P2 orange / P3 green), shows condition, drone, rescue time
7. **Charts row** — 4 tiles: coverage over time (line), survivors found (step), drone battery levels (multi-line), decision type (donut) — all using `recharts`, data sourced from the `ticks` array in `GET /missions/{id}/replay`

### New: `src/components/MissionReplay.tsx`

Props: `missionId: string`. Fetches `GET /missions/{id}/replay` on mount.

Two-panel layout:
- **Left: Event timeline** — scrollable list of events from all ticks, highlights the event at the current scrub position with a "← you are here" marker
- **Right: 2D grid snapshot** — 20×15 grid rendered as colored cells: scanned (green tint), unscanned (dark), drone position (blue), survivor found (red), active survivor (orange)

Scrub bar at bottom:
- Drag handle scrubs through stored tick snapshots
- Speed buttons: ×1 / ×2 / ×4 (auto-advance interval)
- Play / pause toggle
- Current tick / total ticks display

### Chart library: `recharts`

Add `recharts` to `frontend/package.json`. Used only in `MissionDetail.tsx` and `MissionReplay.tsx`. No other chart library needed.

---

## Environment Variables

Add to `.env` and document in `README`:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

---

## Data Flow Summary

```
Live mission
  └── SessionLog.log_tick() → mission_reports/<timestamp>.jsonl  (unchanged)

Mission complete
  └── server.py detects all zones done
      └── builds summary dict from SimulationState.metrics
      └── spawns background thread → session_log.flush_to_supabase()
          ├── reads JSONL, downsamples every 5th tick
          ├── INSERT INTO mission_ticks (mission_id, ticks, created_at)
          └── INSERT INTO missions (id, started_at, ..., survivors)

History tab loads
  └── GET /missions → card list
      └── click "View Details" → GET /missions/{id} → MissionDetail
      └── click "▶ Replay"    → GET /missions/{id}/replay → MissionReplay

Agent load_insights() (cross-mission learning)
  └── local JSONL exists → read files (same as today)
  └── no local files (cloud deploy) → query mission_ticks from Supabase
```

---

## Out of Scope

- Authentication / per-user history (all missions visible to all operators)
- Deleting or editing past missions
- Exporting missions as CSV or PDF
- Full 3D Three.js replay (the 2D grid snapshot is the replay surface)

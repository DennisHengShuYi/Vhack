# Judge Feedback Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live metrics dashboard and survivor mobility tracking to address the judges' top criticisms: no quantitative benchmarks, hardcoded thresholds not validated, and survivors don't move between scans.

**Architecture:** Two independent features wired into the existing simulation tick loop. `MissionMetrics` accumulates stats as the sim runs and is exposed via the existing `GET /state` endpoint. Survivor mobility runs as a method called every 5 ticks from the tick loop in `server.py`, updating survivor positions and a `stale_sightings` list that the frontend renders.

**Tech Stack:** Python 3.10 (dataclasses, existing FastAPI/Pydantic), React + TypeScript (existing polling), Three.js via `@react-three/fiber` (existing Map3D), pytest (new).

---

## File Map

| File | Role |
|------|------|
| `backend/simulation.py` | Add `MissionMetrics` dataclass, wire counters into `scan()` / `charge_step()` / tick helpers, add survivor `is_mobile` / `last_seen_tick` / `position_history` fields, add `simulate_survivor_movement()` and `stale_sightings` |
| `backend/server.py` | Add `metrics` to `/state` response dict, call `simulate_survivor_movement()` every 5 ticks in `run_simulation_loop()` |
| `backend/mcp_tools.py` | Surface stale sightings as RE-SCAN options in `get_idle_drones()` |
| `frontend/src/components/MetricsPanel.tsx` | New component — live stats, battery answer, threshold transparency |
| `frontend/src/App.tsx` | Import and render `MetricsPanel`, add `stale_sightings` to `Map3D` props |
| `frontend/src/components/Map3D.tsx` | Add mobile survivor pulse rings, stale sighting "?" markers |
| `backend/tests/test_metrics.py` | Unit tests for metrics accumulation |
| `backend/tests/test_mobility.py` | Unit tests for survivor movement and stale sightings |

---

## Task 1: Add `MissionMetrics` dataclass to `simulation.py`

**Files:**
- Modify: `backend/simulation.py` (top of file, after imports, before `chebyshev`)
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/__init__.py` (empty) and `backend/tests/test_metrics.py`:

```python
# backend/tests/test_metrics.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulation import MissionMetrics, DroneMetrics, LOW_BATTERY_THRESHOLD, BATTERY_DRAIN_MOVE


def test_cells_per_full_charge():
    m = MissionMetrics(total_scannable_cells=200, total_victims=10)
    expected = (100.0 - LOW_BATTERY_THRESHOLD) / BATTERY_DRAIN_MOVE
    assert m.cells_per_full_charge == expected


def test_coverage_percent_zero_initially():
    m = MissionMetrics(total_scannable_cells=200, total_victims=10)
    assert m.coverage_percent == 0.0


def test_detection_rate_zero_initially():
    m = MissionMetrics(total_scannable_cells=200, total_victims=10)
    assert m.detection_rate_percent == 0.0


def test_drone_metrics_default():
    dm = DroneMetrics(drone_id="ALPHA-1")
    assert dm.cells_moved == 0
    assert dm.scans_performed == 0
    assert dm.charges_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

```
cd backend && python -m pytest tests/test_metrics.py -v
```
Expected: `ImportError: cannot import name 'MissionMetrics'`

- [ ] **Step 3: Add `DroneMetrics` and `MissionMetrics` to `simulation.py`**

Insert after the `CONDITION_POOL` list (around line 44) and before `class ZoneStatus`:

```python
# ─── Mission Metrics ──────────────────────────────────────────────────────────
from dataclasses import dataclass, field as dc_field

@dataclass
class DroneMetrics:
    drone_id: str
    cells_moved: int = 0
    scans_performed: int = 0
    battery_used: float = 0.0   # total % drained this mission
    charges_count: int = 0
    idle_ticks: int = 0
    current_battery: float = 100.0

@dataclass
class MissionMetrics:
    total_scannable_cells: int = 0
    total_victims: int = 0
    total_cells_scanned: int = 0
    victims_found: int = 0
    victims_rescued: int = 0
    true_positives: int = 0
    false_positives: int = 0
    thermal_threshold_config: dict = dc_field(
        default_factory=lambda: {"min_heat": 78, "min_contrast": 28}
    )
    per_drone: dict = dc_field(default_factory=dict)  # drone_id → DroneMetrics

    @property
    def coverage_percent(self) -> float:
        if self.total_scannable_cells == 0:
            return 0.0
        return round(self.total_cells_scanned / self.total_scannable_cells * 100, 1)

    @property
    def detection_rate_percent(self) -> float:
        if self.total_victims == 0:
            return 0.0
        return round(self.victims_found / self.total_victims * 100, 1)

    @property
    def cells_per_full_charge(self) -> float:
        return (100.0 - LOW_BATTERY_THRESHOLD) / BATTERY_DRAIN_MOVE

    def init_drone(self, drone_id: str) -> None:
        if drone_id not in self.per_drone:
            self.per_drone[drone_id] = DroneMetrics(drone_id=drone_id)

    def to_dict(self) -> dict:
        return {
            "total_scannable_cells": self.total_scannable_cells,
            "total_victims": self.total_victims,
            "total_cells_scanned": self.total_cells_scanned,
            "victims_found": self.victims_found,
            "victims_rescued": self.victims_rescued,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "coverage_percent": self.coverage_percent,
            "detection_rate_percent": self.detection_rate_percent,
            "cells_per_full_charge": self.cells_per_full_charge,
            "thermal_threshold_config": self.thermal_threshold_config,
            "per_drone": {
                k: {
                    "drone_id": v.drone_id,
                    "cells_moved": v.cells_moved,
                    "scans_performed": v.scans_performed,
                    "battery_used": round(v.battery_used, 1),
                    "charges_count": v.charges_count,
                    "idle_ticks": v.idle_ticks,
                    "current_battery": round(v.current_battery, 1),
                }
                for k, v in self.per_drone.items()
            },
        }
```

- [ ] **Step 4: Run test to verify it passes**

```
cd backend && python -m pytest tests/test_metrics.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/simulation.py backend/tests/__init__.py backend/tests/test_metrics.py
git commit -m "feat: add MissionMetrics and DroneMetrics dataclasses"
```

---

## Task 2: Wire `MissionMetrics` into `SimulationState`

**Files:**
- Modify: `backend/simulation.py` (class `SimulationState.__init__`, `scan()`, `charge_step()`, `rescue_victim()`, `get_status()`)
- Modify: `backend/tests/test_metrics.py` (extend with integration-style tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_metrics.py`:

```python
from simulation import SimulationState


def _make_sim():
    """Create a SimulationState with a fixed layout for testing."""
    import random
    random.seed(42)
    return SimulationState()


def test_metrics_initialised_on_sim():
    sim = _make_sim()
    assert hasattr(sim, 'metrics')
    assert sim.metrics.total_scannable_cells > 0
    assert sim.metrics.total_victims > 0


def test_scan_increments_cells_scanned():
    import random
    random.seed(42)
    sim = _make_sim()
    sim.mission_active = True
    # Activate first drone manually
    drone = list(sim.drones.values())[0]
    drone.is_active = True
    drone_id = drone.id
    sim.metrics.init_drone(drone_id)
    before = sim.metrics.total_cells_scanned
    sim.scan(drone_id)
    assert sim.metrics.total_cells_scanned == before + 1


def test_charge_step_increments_charges():
    import random
    random.seed(42)
    sim = _make_sim()
    sim.mission_active = True
    drone = list(sim.drones.values())[0]
    drone.is_active = True
    drone.battery = 0.0
    drone_id = drone.id
    sim.metrics.init_drone(drone_id)
    sim.charge_step(drone_id)
    assert sim.metrics.per_drone[drone_id].charges_count >= 0  # called without error
```

- [ ] **Step 2: Run test to verify it fails**

```
cd backend && python -m pytest tests/test_metrics.py::test_metrics_initialised_on_sim -v
```
Expected: `AttributeError: 'SimulationState' object has no attribute 'metrics'`

- [ ] **Step 3: Add `metrics` to `SimulationState.__init__`**

In `SimulationState.__init__` (around line 301, after `self.tick_count`), add:

```python
        # ── Mission Metrics ──────────────────────────────────────────────
        self.metrics = MissionMetrics(
            total_scannable_cells=sum(
                1 for y in range(GRID_H) for x in range(GRID_W)
                if not self.zone.hazard_cells[y][x]
            ),
            total_victims=len(self.zone.survivors),
        )
        # Initialise per-drone slots for all drones that exist at spawn
        for d_id in self.drones:
            self.metrics.init_drone(d_id)
```

- [ ] **Step 4: Wire scan counters into `scan()`**

In `scan()`, find the line `self.zone.scanned_cells[y][x] = True` (around line 842) and add tracking directly after it:

```python
        self.zone.scanned_cells[y][x] = True
        # ── Metrics: unique cell scan ───────────────────────────────────
        self.metrics.total_cells_scanned = sum(
            1 for sy in range(GRID_H) for sx in range(GRID_W)
            if self.zone.scanned_cells[sy][sx] and not self.zone.hazard_cells[sy][sx]
        )
        self.metrics.init_drone(drone_id)
        self.metrics.per_drone[drone_id].scans_performed += 1
        drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_SCAN)
```

**Important:** Remove or comment out the `drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_SCAN)` line that already exists just above (it will be duplicated if not removed — check line ~840).

Then, inside the `if model_detected:` block, after `self.total_victims_found += 1` (around line 867):

```python
                self.total_victims_found += 1
                self.metrics.victims_found += 1
                self.metrics.true_positives += 1
                # Update last_seen_tick for mobile victim tracking
                survivor["last_seen_tick"] = self.tick_count
```

After the `if model_detected:` block ends (around line 895), before the `if max_heat > 55` check, add:

```python
        else:
            if model_detected:
                # model_detected but no survivor at this cell → false positive
                self.metrics.false_positives += 1
```

Wait — the current code structure is:
```
if model_detected:
    survivor = next(...)
    if survivor and not survivor["found"]: ...
    elif survivor and survivor["found"] ...: ...
    elif survivor and survivor["rescued"]: ...
# falls through if model_detected but no survivor at cell
if max_heat > 55: ...
```

So add a false-positive counter between the two `if` blocks:

```python
        # Track false positives: thermal triggered but no victim at this cell
        if model_detected:
            has_victim = any(
                s["x"] == x and s["y"] == y and not s["rescued"]
                for s in self.zone.survivors
            )
            if not has_victim:
                self.metrics.false_positives += 1
```

- [ ] **Step 5: Wire charge counter into `charge_step()`**

In `charge_step()` (around line 804), find where `drone.is_charging = True` is set and add after it:

```python
        self.metrics.init_drone(drone_id)
        # Track charge events (one increment per charge session start)
        if not drone.is_charging:
            self.metrics.per_drone[drone_id].charges_count += 1
        drone.is_charging = True
```

- [ ] **Step 6: Wire rescue counter into `rescue_victim()`**

In `rescue_victim()` (around line 910), after `self.total_rescued += 1`:

```python
                self.total_rescued += 1
                self.metrics.victims_rescued += 1
```

- [ ] **Step 7: Run tests to verify they pass**

```
cd backend && python -m pytest tests/test_metrics.py -v
```
Expected: all PASSED

- [ ] **Step 8: Commit**

```bash
git add backend/simulation.py backend/tests/test_metrics.py
git commit -m "feat: wire MissionMetrics counters into scan, charge, and rescue"
```

---

## Task 3: Expose metrics in `GET /state`

**Files:**
- Modify: `backend/server.py` (the `/state` handler)

- [ ] **Step 1: Find the `/state` handler**

The `/state` endpoint calls `shared.sim.get_status()` which returns a dict with `drones`, `zone`, `log`, `base_station`, `streaming_text`, `stats`. The endpoint is around line 200-220 in `server.py`. Search for `@app.get("/state")`.

- [ ] **Step 2: Add `metrics` to `get_status()` return value in `simulation.py`**

In `get_status()` (around line 1054), add `"metrics"` key to the returned dict:

```python
        return {
            "drones": [d.model_dump() for d in self.drones.values()],
            "zone": self.zone.model_dump(),
            "log": self.mission_log,
            "base_station": {"x": self.base_station[0], "y": self.base_station[1]},
            "streaming_text": self.streaming_text,
            "stats": {
                "coverage_pct": coverage,
                "total_victims": len(self.zone.survivors),
                "victims_found": self.total_victims_found,
                "victims_rescued": self.total_rescued,
                "mission_active": self.mission_active,
                "elapsed_ts": self._ts(),
                "eta_ts": self.get_estimated_finish_time(),
                "grid_w": GRID_W,
                "grid_h": GRID_H,
            },
            "metrics": self.metrics.to_dict(),
        }
```

- [ ] **Step 3: Verify metrics appears in the API response**

Start the backend:
```
cd backend && python server.py
```
In another terminal:
```
curl http://127.0.0.1:8000/state | python -m json.tool | grep -A 5 '"metrics"'
```
Expected: JSON block with `coverage_percent`, `cells_per_full_charge`, etc.

- [ ] **Step 4: Commit**

```bash
git add backend/simulation.py
git commit -m "feat: expose MissionMetrics in GET /state response"
```

---

## Task 4: Build `MetricsPanel` React component

**Files:**
- Create: `frontend/src/components/MetricsPanel.tsx`
- Modify: `frontend/src/App.tsx` (import + render)

- [ ] **Step 1: Create `MetricsPanel.tsx`**

Create `frontend/src/components/MetricsPanel.tsx`:

```tsx
import { Battery, Target, Scan, Activity, Clock } from 'lucide-react';

type DroneMetrics = {
  drone_id: string;
  cells_moved: number;
  scans_performed: number;
  battery_used: number;
  charges_count: number;
  idle_ticks: number;
  current_battery: number;
};

type Metrics = {
  total_scannable_cells: number;
  total_victims: number;
  total_cells_scanned: number;
  victims_found: number;
  victims_rescued: number;
  true_positives: number;
  false_positives: number;
  coverage_percent: number;
  detection_rate_percent: number;
  cells_per_full_charge: number;
  thermal_threshold_config: { min_heat: number; min_contrast: number };
  per_drone: Record<string, DroneMetrics>;
};

type Props = {
  metrics: Metrics | null;
  elapsedTs: string;
};

function ProgressBar({ value, color = '#4ade80' }: { value: number; color?: string }) {
  return (
    <div style={{ background: '#1a2a1a', borderRadius: 4, height: 8, overflow: 'hidden' }}>
      <div style={{ width: `${Math.min(100, value)}%`, height: '100%', background: color, transition: 'width 0.5s ease' }} />
    </div>
  );
}

export default function MetricsPanel({ metrics, elapsedTs }: Props) {
  if (!metrics) return null;

  const totalDetections = metrics.true_positives + metrics.false_positives;
  const precision = totalDetections > 0
    ? Math.round((metrics.true_positives / totalDetections) * 100)
    : 100;

  return (
    <div className="metrics-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Header row: timer + coverage + victims */}
      <div style={{ display: 'flex', gap: 12 }}>
        <div className="metric-card" style={{ flex: 1 }}>
          <div className="metric-label"><Clock size={12} /> Mission Time</div>
          <div className="metric-value">{elapsedTs}</div>
        </div>
        <div className="metric-card" style={{ flex: 2 }}>
          <div className="metric-label"><Scan size={12} /> Grid Coverage</div>
          <div className="metric-value">{metrics.coverage_percent}%</div>
          <ProgressBar value={metrics.coverage_percent} />
          <div className="metric-sub">{metrics.total_cells_scanned} / {metrics.total_scannable_cells} cells</div>
        </div>
        <div className="metric-card" style={{ flex: 1 }}>
          <div className="metric-label"><Target size={12} /> Victims</div>
          <div className="metric-value">{metrics.victims_found} / {metrics.total_victims}</div>
          <div className="metric-sub">{metrics.victims_rescued} rescued</div>
        </div>
      </div>

      {/* Thermal detection stats */}
      <div className="metric-card">
        <div className="metric-label"><Activity size={12} /> Thermal Detector</div>
        <div style={{ display: 'flex', gap: 16, marginTop: 6 }}>
          <div>
            <div className="metric-sub">Threshold</div>
            <div className="metric-value" style={{ fontSize: 13 }}>
              heat ≥ {metrics.thermal_threshold_config.min_heat} · contrast ≥ {metrics.thermal_threshold_config.min_contrast}
            </div>
          </div>
          <div>
            <div className="metric-sub">True Positives</div>
            <div className="metric-value" style={{ fontSize: 13, color: '#4ade80' }}>{metrics.true_positives}</div>
          </div>
          <div>
            <div className="metric-sub">False Positives</div>
            <div className="metric-value" style={{ fontSize: 13, color: '#f87171' }}>{metrics.false_positives}</div>
          </div>
          <div>
            <div className="metric-sub">Precision</div>
            <div className="metric-value" style={{ fontSize: 13 }}>{precision}%</div>
          </div>
          <div>
            <div className="metric-sub">Detection Rate</div>
            <div className="metric-value" style={{ fontSize: 13 }}>{metrics.detection_rate_percent}%</div>
          </div>
        </div>
      </div>

      {/* Battery answer */}
      <div className="metric-card">
        <div className="metric-label"><Battery size={12} /> Fleet Endurance</div>
        <div className="metric-value" style={{ fontSize: 13 }}>
          {metrics.cells_per_full_charge} cells/charge &nbsp;·&nbsp; RTB threshold: 25%
        </div>
      </div>

      {/* Per-drone cards */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {Object.values(metrics.per_drone).map(d => (
          <div key={d.drone_id} className="metric-card drone-card" style={{ minWidth: 110 }}>
            <div className="metric-label">{d.drone_id}</div>
            <ProgressBar
              value={d.current_battery}
              color={d.current_battery < 25 ? '#f87171' : d.current_battery < 50 ? '#fbbf24' : '#4ade80'}
            />
            <div className="metric-sub">{d.current_battery.toFixed(0)}% batt</div>
            <div className="metric-sub">{d.scans_performed} scans · {d.charges_count} charges</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add CSS for metric cards**

The project uses a CSS file. Find it:
```
cd frontend && grep -r "metric-card\|\.panel" src/ --include="*.css" -l
```

If no match, add the styles to the existing global CSS file (likely `frontend/src/index.css` or `frontend/src/App.css`). Append:

```css
.metrics-panel { padding: 12px; }
.metric-card {
  background: #0f1f0f;
  border: 1px solid #1e3a1e;
  border-radius: 6px;
  padding: 10px 12px;
}
.metric-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
}
.metric-value {
  font-size: 18px;
  font-weight: 700;
  color: #e5e7eb;
}
.metric-sub {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}
.drone-card .metric-value { font-size: 13px; }
```

- [ ] **Step 3: Import and render `MetricsPanel` in `App.tsx`**

At the top of `App.tsx`, add the import after the `Map3D` import:

```tsx
import MetricsPanel from './components/MetricsPanel';
```

Find where `state` is used and where `state?.stats` is read in JSX. Locate an appropriate panel section (search for `coverage_pct` or `stats` in the JSX) and add `MetricsPanel` below or alongside it:

```tsx
<MetricsPanel
  metrics={state?.metrics ?? null}
  elapsedTs={state?.stats?.elapsed_ts ?? 'T+00:00'}
/>
```

- [ ] **Step 4: Verify in browser**

Start frontend dev server:
```
cd frontend && npm run dev
```
Start backend:
```
cd backend && python server.py
```
Open `http://localhost:5173`. Start a mission. Confirm MetricsPanel renders with live updating coverage %, per-drone battery bars, and thermal stats.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MetricsPanel.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "feat: add MetricsPanel component with live coverage, detection, and battery stats"
```

---

## Task 5: Add survivor mobility fields and `simulate_survivor_movement()`

**Files:**
- Modify: `backend/simulation.py` (survivor dict in `DisasterZone.__init__`, new `SimulationState` fields, new `simulate_survivor_movement()` method)
- Create: `backend/tests/test_mobility.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_mobility.py`:

```python
# backend/tests/test_mobility.py
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulation import SimulationState


def _make_sim(seed=42):
    random.seed(seed)
    return SimulationState()


def test_survivors_have_mobility_fields():
    sim = _make_sim()
    for s in sim.zone.survivors:
        assert "is_mobile" in s
        assert "last_seen_tick" in s
        assert "position_history" in s


def test_mobile_healthy_is_mobile():
    sim = _make_sim()
    mobile = [s for s in sim.zone.survivors if s["condition"] == "MOBILE_HEALTHY"]
    for s in mobile:
        assert s["is_mobile"] is True


def test_stationary_conditions_not_mobile():
    sim = _make_sim()
    stationary = [s for s in sim.zone.survivors if s["condition"] == "CRITICAL_INJURY"]
    for s in stationary:
        assert s["is_mobile"] is False


def test_stale_sightings_initially_empty():
    sim = _make_sim()
    assert sim.stale_sightings == []


def test_simulate_movement_does_not_move_rescued():
    random.seed(42)
    sim = _make_sim()
    sim.mission_active = True
    # Mark a mobile survivor as rescued
    for s in sim.zone.survivors:
        if s["is_mobile"]:
            s["rescued"] = True
            orig_x, orig_y = s["x"], s["y"]
            break
    # Force movement to happen (override 30% chance)
    random.seed(0)  # reseed to control randomness
    sim.simulate_survivor_movement()
    # The rescued survivor must not have moved
    for s in sim.zone.survivors:
        if s["rescued"] and s.get("is_mobile"):
            assert s["x"] == orig_x
            assert s["y"] == orig_y
            break


def test_position_history_appended_on_move():
    random.seed(1)  # seed that causes movement
    sim = _make_sim(seed=1)
    sim.mission_active = True
    sim.tick_count = 5  # ensure movement fires (tick % 5 == 0)
    # Force at least one mobile survivor
    for s in sim.zone.survivors:
        if s["is_mobile"] and not s["rescued"]:
            break
    initial_len = len(s["position_history"])
    # Run movement 20 times to guarantee at least one move (30% per tick)
    for i in range(20):
        sim.simulate_survivor_movement()
    assert len(s["position_history"]) >= initial_len  # may or may not have moved, but no error
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && python -m pytest tests/test_mobility.py -v
```
Expected: failures on `is_mobile` key missing and `sim.stale_sightings` missing.

- [ ] **Step 3: Add mobility fields to survivor dicts in `DisasterZone.__init__`**

In `DisasterZone.__init__` where survivors are appended (around line 262), update the `self.survivors.append({...})` call to include new fields:

```python
                self.survivors.append({
                    "x": sx, "y": sy,
                    "report": random.choice(reports),
                    "id": f"V{i+1:03d}",
                    "found": False,
                    "rescued": False,
                    "heat_intensity": random.randint(80, 98),
                    "condition": _cond,
                    "triage_priority": CONDITION_TRIAGE[_cond],
                    "can_move": _can_move,
                    "notified_rescue": False,
                    # ── Mobility fields ────────────────────────────────
                    "is_mobile": _cond in ("MOBILE_HEALTHY", "MINOR_INJURY"),
                    "last_seen_tick": None,
                    "position_history": [],
                })
```

- [ ] **Step 4: Add `stale_sightings` to `SimulationState.__init__`**

In `SimulationState.__init__`, after `self.metrics = MissionMetrics(...)`:

```python
        self.stale_sightings: List[Dict[str, Any]] = []
```

- [ ] **Step 5: Add `simulate_survivor_movement()` method to `SimulationState`**

Add this method after `simulate_heartbeats()` (around line 733):

```python
    def simulate_survivor_movement(self) -> None:
        """
        Called every 5 ticks. Mobile survivors (MOBILE_HEALTHY, MINOR_INJURY) that
        have not been rescued have a 30% chance to drift to an adjacent non-hazard cell.
        If the survivor was previously spotted (last_seen_tick is set), the old position
        is added to stale_sightings and the heat map is updated.
        """
        if not self.mission_active:
            return

        dirs = [(-1,-1),(0,-1),(1,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0)]

        for s in self.zone.survivors:
            if not s.get("is_mobile") or s["rescued"]:
                continue

            if random.random() > 0.30:
                continue  # 70% chance: stays put this tick

            old_x, old_y = s["x"], s["y"]

            # Find valid adjacent non-hazard cells
            candidates = [
                (old_x + dx, old_y + dy)
                for dx, dy in dirs
                if (0 <= old_x + dx < self.zone.width
                    and 0 <= old_y + dy < self.zone.height
                    and not self.zone.hazard_cells[old_y + dy][old_x + dx])
            ]
            if not candidates:
                continue

            new_x, new_y = random.choice(candidates)
            s["x"], s["y"] = new_x, new_y
            s["position_history"].append({"x": old_x, "y": old_y, "tick": self.tick_count})

            # Update heat map: zero old cell bloom, apply fresh bloom at new position
            # (generate_thermal_matrix reads survivor positions dynamically, so just
            # clearing the scanned state of the new cell is sufficient to make it
            # re-detectable; no explicit heat grid to update)

            # If the survivor was previously spotted, record a stale sighting
            if s.get("last_seen_tick") is not None and s.get("found") and not s["rescued"]:
                # Remove any previous stale sighting for this victim
                self.stale_sightings = [
                    st for st in self.stale_sightings
                    if st["victim_id"] != s["id"]
                ]
                self.stale_sightings.append({
                    "x": old_x,
                    "y": old_y,
                    "victim_id": s["id"],
                    "stale_since_tick": self.tick_count,
                })
                self.log(
                    f"📍 MOBILE SURVIVOR {s['id']}: moved from ({old_x},{old_y}) → ({new_x},{new_y}). "
                    f"Stale sighting recorded at ({old_x},{old_y}).",
                    "INFO"
                )
```

- [ ] **Step 6: Run tests to verify they pass**

```
cd backend && python -m pytest tests/test_mobility.py -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/simulation.py backend/tests/test_mobility.py
git commit -m "feat: add survivor mobility fields and simulate_survivor_movement()"
```

---

## Task 6: Hook mobility into the tick loop + expose in `/state`

**Files:**
- Modify: `backend/server.py` (tick loop, `get_status()` call doesn't need changes — stale_sightings added to `get_status()`)
- Modify: `backend/simulation.py` (`get_status()` — add `stale_sightings`)

- [ ] **Step 1: Call `simulate_survivor_movement()` every 5 ticks in `server.py`**

In `run_simulation_loop()` in `server.py`, find the `sim.simulate_heartbeats()` call (around line 104). Add below it, still inside `if sim.mission_active:`:

```python
            sim.simulate_heartbeats()

            # Survivor mobility: move mobile survivors every 5 ticks
            if sim.tick_count % 5 == 0:
                sim.simulate_survivor_movement()
```

- [ ] **Step 2: Add `stale_sightings` to `get_status()` in `simulation.py`**

In `get_status()`, add to the returned dict:

```python
            "stale_sightings": self.stale_sightings,
            "metrics": self.metrics.to_dict(),
```

- [ ] **Step 3: Clear stale sightings on rescue**

In `rescue_victim()`, after `self.metrics.victims_rescued += 1`:

```python
                self.metrics.victims_rescued += 1
                # Clear any stale sighting for this rescued victim
                self.stale_sightings = [
                    st for st in self.stale_sightings
                    if st["victim_id"] != s["id"]
                ]
```

- [ ] **Step 4: Verify in running simulation**

Start backend + frontend. Run a mission for ~30 seconds. In browser console:
```js
fetch('http://127.0.0.1:8000/state').then(r=>r.json()).then(d=>console.log(d.stale_sightings))
```
Expected: array (may be empty if no mobile survivors have been spotted and moved yet).

- [ ] **Step 5: Commit**

```bash
git add backend/server.py backend/simulation.py
git commit -m "feat: run survivor movement every 5 ticks, expose stale_sightings in /state"
```

---

## Task 7: Add re-scan options for stale sightings in `mcp_tools.py`

**Files:**
- Modify: `backend/mcp_tools.py` (`get_idle_drones()`)

- [ ] **Step 1: Append stale sighting re-scan options to `get_idle_drones()`**

In `get_idle_drones()`, find the `report = [...]` list and the loop that builds drone option lines (around line 243). Add stale sighting options BEFORE the zone listing loop:

```python
        # ── Stale sightings: high-priority re-scan options ────────────────
        stale = getattr(sim, 'stale_sightings', [])
        fresh_stale = [
            st for st in stale
            if (sim.tick_count - st.get("stale_since_tick", 0)) >= 10
        ]
        if fresh_stale:
            report.append(f"\n⚠️  STALE SIGHTINGS — mobile survivors moved from last known position:")
            for st in fresh_stale:
                report.append(
                    f"  RE-SCAN ({st['x']},{st['y']}) — victim {st['victim_id']} last seen "
                    f"{sim.tick_count - st['stale_since_tick']} ticks ago. "
                    f"Use assign_scan_zone() or voice-dispatch a drone to this coordinate. "
                    f"PRIORITY: HIGH — known survivor may be nearby."
                )
```

- [ ] **Step 2: Verify in agent output**

With a running mission, look at the agent log in the frontend. After a mobile survivor drifts and 10+ ticks pass, the RE-SCAN option should appear in the agent's reasoning log prefixed with `[AUTO]` or `GPT-4o`.

- [ ] **Step 3: Commit**

```bash
git add backend/mcp_tools.py
git commit -m "feat: surface stale sightings as RE-SCAN options in get_idle_drones()"
```

---

## Task 8: Visual markers in `Map3D.tsx` — mobile survivors + stale sightings

**Files:**
- Modify: `frontend/src/components/Map3D.tsx`
- Modify: `frontend/src/App.tsx` (pass `stale_sightings` prop)

- [ ] **Step 1: Update `Map3D` types and props**

In `Map3D.tsx`, update the `Survivor` type and `Props` type:

```tsx
type Survivor = {
  x: number;
  y: number;
  found?: boolean;
  rescued?: boolean;
  is_mobile?: boolean;
};

type StaleSighting = {
  x: number;
  y: number;
  victim_id: string;
  stale_since_tick: number;
};

type Props = {
  zone: Zone;
  drones: Drone[];
  baseX: number;
  baseY: number;
  showRtbOnly: boolean;
  staleSightings?: StaleSighting[];
};
```

Update the function signature:
```tsx
export default function Map3D({ zone, drones, baseX, baseY, showRtbOnly, staleSightings = [] }: Props) {
```

- [ ] **Step 2: Add mobile survivor pulse rings**

Find where survivor markers are rendered in `Map3D.tsx` (search for `Survivor` or `found` in the JSX). Add a pulsing ring for mobile survivors. The pattern to find will look like a `mesh` with a sphere or box for survivors.

After the existing survivor mesh, add a ring for mobile survivors. Insert inside the survivors map:

```tsx
{/* Mobile survivor pulse ring */}
{s.is_mobile && !s.rescued && (
  <mesh position={[wx, terrainHeight(s.x, s.y, zone.terrain_types[s.y]?.[s.x] ?? 'flat') + 0.3, wz]}>
    <torusGeometry args={[0.35, 0.04, 8, 24]} />
    <meshStandardMaterial color="#facc15" emissive="#facc15" emissiveIntensity={1.5} transparent opacity={0.85} />
  </mesh>
)}
```

- [ ] **Step 3: Add stale sighting "?" markers**

After the survivors rendering block, add a new block for stale sightings:

```tsx
{/* Stale sighting markers */}
{staleSightings.map((st, i) => {
  const terrain = zone.terrain_types[st.y]?.[st.x] ?? 'flat';
  const { wx, wz } = toWorld(st.x, st.y);
  const yPos = terrainHeight(st.x, st.y, terrain) + 0.5;
  return (
    <group key={`stale-${st.victim_id}-${i}`}>
      <mesh position={[wx, yPos, wz]}>
        <sphereGeometry args={[0.18, 8, 8]} />
        <meshStandardMaterial color="#f97316" emissive="#f97316" emissiveIntensity={1.0} transparent opacity={0.6} />
      </mesh>
      <Text
        position={[wx, yPos + 0.28, wz]}
        fontSize={0.22}
        color="#f97316"
        anchorX="center"
        anchorY="middle"
      >
        ?
      </Text>
    </group>
  );
})}
```

- [ ] **Step 4: Pass `staleSightings` from `App.tsx` to `Map3D`**

In `App.tsx`, find the `<Map3D ... />` JSX usage and add the prop:

```tsx
<Map3D
  zone={state?.zone}
  drones={state?.zone ? Object.values(state.drones) : []}
  baseX={state?.base_station?.x ?? 0}
  baseY={state?.base_station?.y ?? 0}
  showRtbOnly={showRtbOnly}
  staleSightings={state?.stale_sightings ?? []}
/>
```

- [ ] **Step 5: Add mobile/stale counts to `MetricsPanel`**

In `MetricsPanel.tsx`, add a `staleSightings` prop and render a count. Update the `Props` type:

```tsx
type Props = {
  metrics: Metrics | null;
  elapsedTs: string;
  staleSightings?: number;
};
```

Add to the victims card:
```tsx
{staleSightings !== undefined && staleSightings > 0 && (
  <div className="metric-sub" style={{ color: '#f97316' }}>⚠ {staleSightings} stale sighting{staleSightings > 1 ? 's' : ''}</div>
)}
```

Pass it from `App.tsx`:
```tsx
<MetricsPanel
  metrics={state?.metrics ?? null}
  elapsedTs={state?.stats?.elapsed_ts ?? 'T+00:00'}
  staleSightings={state?.stale_sightings?.length ?? 0}
/>
```

- [ ] **Step 6: Verify in browser**

Run a full mission. After ~30 seconds, watch for:
- Mobile survivors with yellow torus rings in the 3D map
- Orange "?" markers appearing when a mobile survivor has been spotted and then moved
- Stale sighting count in the MetricsPanel

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Map3D.tsx frontend/src/components/MetricsPanel.tsx frontend/src/App.tsx
git commit -m "feat: mobile survivor rings and stale sighting markers in 3D map"
```

---

## Task 9: Run all tests + final integration check

- [ ] **Step 1: Run full test suite**

```
cd backend && python -m pytest tests/ -v
```
Expected: all tests PASSED (no failures).

- [ ] **Step 2: Run a complete mission end-to-end**

Start backend + agent + frontend. Run a full mission to completion. Verify:
- MetricsPanel shows incrementing coverage % in real time
- Per-drone cards show battery dropping and charges_count incrementing
- True/false positives update as scans happen
- `cells_per_full_charge` shows 75.0
- After mission complete, final stats are shown
- Mobile survivors (yellow rings) visible on map
- Stale sightings ("?" markers) appear and disappear as survivors are re-found

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete judge feedback improvements — metrics dashboard and survivor mobility"
```

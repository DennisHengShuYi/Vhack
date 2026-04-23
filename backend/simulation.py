"""
Disaster Zone Simulation — 20×15 grid with survivor thermal scanning.
This is the core simulation that the MCP tools control.
"""
import random
import time
import math
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

# ─── Grid Constants ────────────────────────────────────────────────────────────
GRID_W               = 20
GRID_H               = 15
CHARGE_RATE          = 34.0   # % per charge_step call
BATTERY_DRAIN_MOVE   = 1.0    # % per cell moved
BATTERY_DRAIN_SCAN   = 1.0    # % per thermal scan
LOW_BATTERY_THRESHOLD = 25.0  # % — recall threshold
BATTERY_RETURN_RESERVE = 8.0  # % — emergency reserve after reaching base
TERRAIN_SCAN_WEIGHT: Dict[str, int] = {'hazard': 7, 'city': 5, 'forest': 2, 'flat': 1}
NUM_DRONES           = 5

# ─── Victim Condition Constants ────────────────────────────────────────────────
CONDITION_TRIAGE: Dict[str, str] = {
    "CRITICAL_INJURY": "P1-CRITICAL",
    "UNCONSCIOUS":     "P1-CRITICAL",
    "CARDIAC_EVENT":   "P1-CRITICAL",
    "MODERATE_INJURY": "P2-URGENT",
    "TRAPPED_STABLE":  "P2-URGENT",
    "DEHYDRATION":     "P2-URGENT",
    "SHOCK":           "P2-URGENT",
    "MINOR_INJURY":    "P3-STABLE",
    "MOBILE_HEALTHY":  "P3-STABLE",
}
CONDITION_POOL = [
    "CRITICAL_INJURY", "CRITICAL_INJURY", "CRITICAL_INJURY",
    "UNCONSCIOUS",     "UNCONSCIOUS",
    "CARDIAC_EVENT",
    "MODERATE_INJURY", "MODERATE_INJURY",
    "TRAPPED_STABLE",  "TRAPPED_STABLE",
    "DEHYDRATION",     "SHOCK",
    "MINOR_INJURY",    "MINOR_INJURY",
    "MOBILE_HEALTHY",
]

# ─── Mission Metrics ──────────────────────────────────────────────────────────

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
    # --- Performance KPIs ---
    mission_start_time: Optional[float] = None
    first_find_tick: Optional[int] = None
    planning_latencies: list = dc_field(default_factory=list)
    battery_consumed_total: float = 0.0

    def record_planning_latency(self, ms: float) -> None:
        self.planning_latencies.append(ms)

    def record_first_find(self, tick: int) -> None:
        if self.first_find_tick is None:
            self.first_find_tick = tick

    @property
    def avg_planning_latency_ms(self) -> float:
        if not self.planning_latencies:
            return 0.0
        return round(sum(self.planning_latencies) / len(self.planning_latencies), 1)

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
            "performance": {
                "avg_planning_latency_ms": self.avg_planning_latency_ms,
                "first_find_tick": self.first_find_tick,
                "battery_consumed_total": round(self.battery_consumed_total, 1),
            },
        }

@dataclass
class Lead:
    id: str
    tick: int
    lang: str           # EN / BM / TL / ID / TH
    raw: str
    english: str
    x: Optional[int] = None    # None if UNGROUNDED
    y: Optional[int] = None
    urgency: str = "STABLE"        # CRITICAL / URGENT / STABLE
    status: str = "PENDING_GROUND" # PENDING_GROUND / GROUNDED / UNGROUNDED / INVESTIGATING / RESOLVED

@dataclass
class TimelineEvent:
    id: str
    tick: int
    ts: str             # ISO timestamp string
    kind: str           # DECISION / LEAD_INVESTIGATE / BRAIN_SWITCH / CONTRACT / ERROR / TOOL_CALL
    brain: str          # CLOUD / EDGE / RULES
    duration_ms: float
    payload: dict       # kind-specific data


class ZoneStatus(Enum):
    UNSCANNED = "UNSCANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"

class Zone(BaseModel):
    id: str
    sx: int
    sy: int
    ex: int
    ey: int
    status: ZoneStatus = ZoneStatus.UNSCANNED
    assigned_to: Optional[str] = None
    residual_path: List[List[int]] = []
    completed_tick: Optional[int] = None
    started_tick: Optional[int] = None

def chebyshev(x1: int, y1: int, x2: int, y2: int) -> int:
    return max(abs(x2 - x1), abs(y2 - y1))

class Drone(BaseModel):
    id: str
    x: int = 0
    y: int = 0
    base_x: int = 0
    base_y: int = 0
    battery: float = 100.0
    is_active: bool = False       # False until heartbeat connects the drone
    join_tick: int = 0            # Tick at which this drone first comes online
    is_charging: bool = False
    is_waiting_response: bool = False
    returning_to_base: bool = False
    mission_complete_rtb: bool = False
    status: str = "IDLE"
    target_x: Optional[int] = None
    target_y: Optional[int] = None
    victim_report: Optional[str] = None
    last_thermal_matrix: Optional[List[List[int]]] = None
    last_thermal_scan: Optional[Dict[str, Any]] = None
    charge_cycles: int = 0
    status_label: str = "OFFLINE"
    path_history: List[List[int]] = []
    is_guiding: bool = False
    guiding_victim_id: Optional[str] = None
    voice_override: bool = False
    original_pos: Optional[List[int]] = None
    path_queue: List[List[int]] = []
    scanned_grids: int = 0
    assigned_zone_id: Optional[str] = None
    pending_zone_id: Optional[str] = None  # residual zone reserved for this drone after current job


class DisasterZone(BaseModel):
    width: int = GRID_W
    height: int = GRID_H
    num_victims: int = 0  # 0 = random (10–15)
    survivors: List[Dict[str, Any]] = []
    scanned_cells: List[List[bool]] = []
    hazard_cells: List[List[bool]] = []
    terrain_types: List[List[str]] = []
    zones: Dict[str, Zone] = {}

    def __init__(self, **data):
        super().__init__(**data)
        if not self.scanned_cells:
            self.scanned_cells = [[False] * self.width for _ in range(self.height)]
        if not self.hazard_cells:
            self.hazard_cells = [[False] * self.width for _ in range(self.height)]

        if not self.terrain_types:
            self.terrain_types = [['flat'] * self.width for _ in range(self.height)]

            # BFS-grow a connected region of `label` from a seed point
            def grow_blob(sx: int, sy: int, label: str, target: int):
                if self.terrain_types[sy][sx] != 'flat':
                    return
                self.terrain_types[sy][sx] = label
                frontier = [(sx, sy)]
                count = 1
                dirs = [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]
                while count < target and frontier:
                    idx = random.randint(0, len(frontier) - 1)
                    ox, oy = frontier[idx]
                    random.shuffle(dirs)
                    grew = False
                    for dx, dy in dirs:
                        nx2, ny2 = ox + dx, oy + dy
                        if (1 <= nx2 < self.width - 1 and 1 <= ny2 < self.height - 1
                                and self.terrain_types[ny2][nx2] == 'flat'):
                            self.terrain_types[ny2][nx2] = label
                            frontier.append((nx2, ny2))
                            count += 1
                            grew = True
                            if count >= target:
                                return
                            break
                    if not grew:
                        frontier.pop(idx)

            # ── 1. City: one large urban district (rectangle core + L-arm extension) ──
            # Core block: 8–12 wide × 5–8 tall  (~40–96 cells)
            cw = random.randint(8, 12)
            ch = random.randint(5, 8)
            cx0 = random.randint(1, self.width  - cw - 1)
            cy0 = random.randint(1, self.height - ch - 1)
            for gy in range(cy0, cy0 + ch):
                for gx in range(cx0, cx0 + cw):
                    self.terrain_types[gy][gx] = 'city'
            # Extension arm (L or T shape adds 10–25 more city cells)
            arm_w = random.randint(3, 5)
            arm_h = random.randint(3, 5)
            side = random.choice(['right', 'bottom', 'left', 'top'])
            if side == 'right' and cx0 + cw + arm_w < self.width - 1:
                ax = cx0 + cw
                ay = cy0 + random.randint(0, max(0, ch - arm_h))
                for gy in range(ay, min(ay + arm_h, self.height - 1)):
                    for gx in range(ax, min(ax + arm_w, self.width - 1)):
                        self.terrain_types[gy][gx] = 'city'
            elif side == 'bottom' and cy0 + ch + arm_h < self.height - 1:
                ax = cx0 + random.randint(0, max(0, cw - arm_w))
                ay = cy0 + ch
                for gy in range(ay, min(ay + arm_h, self.height - 1)):
                    for gx in range(ax, min(ax + arm_w, self.width - 1)):
                        self.terrain_types[gy][gx] = 'city'
            elif side == 'left' and cx0 - arm_w >= 1:
                ax = cx0 - arm_w
                ay = cy0 + random.randint(0, max(0, ch - arm_h))
                for gy in range(ay, min(ay + arm_h, self.height - 1)):
                    for gx in range(ax, ax + arm_w):
                        self.terrain_types[gy][gx] = 'city'
            elif side == 'top' and cy0 - arm_h >= 1:
                ax = cx0 + random.randint(0, max(0, cw - arm_w))
                ay = cy0 - arm_h
                for gy in range(ay, ay + arm_h):
                    for gx in range(ax, min(ax + arm_w, self.width - 1)):
                        self.terrain_types[gy][gx] = 'city'

            # ── 1b. Hazard: one small BFS blob grown strictly inside city cells ──
            # Hazard cells are a *label*, not an impassability marker — drones can
            # still traverse them. The higher scan weight (7 vs city 5) makes them
            # the top survivor-probability tier.
            city_cells = [
                (x, y)
                for y in range(1, self.height - 1)
                for x in range(1, self.width - 1)
                if self.terrain_types[y][x] == 'city'
            ]
            if city_cells:
                seed = random.choice(city_cells)
                self.terrain_types[seed[1]][seed[0]] = 'hazard'
                frontier = [seed]
                target = random.randint(5, 10)
                count = 1
                dirs_h = [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]
                while count < target and frontier:
                    idx = random.randint(0, len(frontier) - 1)
                    ox, oy = frontier[idx]
                    random.shuffle(dirs_h)
                    grew = False
                    for dx, dy in dirs_h:
                        nx2, ny2 = ox + dx, oy + dy
                        if (0 <= nx2 < self.width and 0 <= ny2 < self.height
                                and self.terrain_types[ny2][nx2] == 'city'):
                            self.terrain_types[ny2][nx2] = 'hazard'
                            frontier.append((nx2, ny2))
                            count += 1
                            grew = True
                            if count >= target:
                                break
                            break
                    if not grew:
                        frontier.pop(idx)

            # ── 2. Forest: 1–2 large contiguous woodland patches (BFS-grown) ──
            for _ in range(random.randint(1, 2)):
                fsize = random.randint(25, 35)
                for _attempt in range(40):
                    fx = random.randint(1, self.width - 2)
                    fy = random.randint(1, self.height - 2)
                    if self.terrain_types[fy][fx] == 'flat':
                        grow_blob(fx, fy, 'forest', fsize)
                        break

            # ── 3. Lake: one connected water body (compact organic blob) ──
            for _attempt in range(40):
                lx = random.randint(2, self.width - 3)
                ly = random.randint(2, self.height - 3)
                if self.terrain_types[ly][lx] == 'flat':
                    grow_blob(lx, ly, 'lake', random.randint(10, 18))
                    break

            # ── 4. Keep base-station corner (0,0) accessible ──
            self.terrain_types[0][0] = 'flat'

            # ── 5. Lake cells are impassable ──
            for y in range(self.height):
                for x in range(self.width):
                    if self.terrain_types[y][x] == 'lake':
                        self.hazard_cells[y][x] = True

        if not self.zones:
            # 12 zones: 4 columns × 3 rows of 5×5 cells each
            self.zones = {
                "Z0":  Zone(id="Z0",  sx=0,  sy=0,  ex=4,  ey=4),
                "Z1":  Zone(id="Z1",  sx=5,  sy=0,  ex=9,  ey=4),
                "Z2":  Zone(id="Z2",  sx=10, sy=0,  ex=14, ey=4),
                "Z3":  Zone(id="Z3",  sx=15, sy=0,  ex=19, ey=4),
                "Z4":  Zone(id="Z4",  sx=0,  sy=5,  ex=4,  ey=9),
                "Z5":  Zone(id="Z5",  sx=5,  sy=5,  ex=9,  ey=9),
                "Z6":  Zone(id="Z6",  sx=10, sy=5,  ex=14, ey=9),
                "Z7":  Zone(id="Z7",  sx=15, sy=5,  ex=19, ey=9),
                "Z8":  Zone(id="Z8",  sx=0,  sy=10, ex=4,  ey=14),
                "Z9":  Zone(id="Z9",  sx=5,  sy=10, ex=9,  ey=14),
                "Z10": Zone(id="Z10", sx=10, sy=10, ex=14, ey=14),
                "Z11": Zone(id="Z11", sx=15, sy=10, ex=19, ey=14),
            }
        if not self.survivors:
            num = self.num_victims if self.num_victims > 0 else random.randint(10, 15)
            reports = [
                "Family of 4 trapped under rubble",
                "Injured individual — possible fracture",
                "Medical emergency — unconscious person",
                "Child separated from parents",
                "Elderly person needing evacuation",
                "Workers in collapsed building",
                "SOS signal — weak thermal signature",
                "Survivor with broken leg near wall",
            ]
            TERRAIN_WEIGHTS = {'hazard': 7, 'city': 5, 'forest': 2, 'flat': 1, 'lake': 0}

            # Build candidate pool weighted by terrain
            pool = []
            for sy in range(self.height):
                for sx in range(self.width):
                    w = TERRAIN_WEIGHTS.get(self.terrain_types[sy][sx], 1)
                    pool.extend([(sx, sy)] * w)

            random.shuffle(pool)
            placed = set()
            seen_in_pool: list = []
            for coord in pool:
                if coord not in placed and self.terrain_types[coord[1]][coord[0]] != 'lake':
                    seen_in_pool.append(coord)
                    placed.add(coord)
                if len(placed) >= num:
                    break

            for i, (sx, sy) in enumerate(seen_in_pool[:num]):
                _cond = random.choice(CONDITION_POOL)
                self.survivors.append({
                    "x": sx, "y": sy,
                    "report": random.choice(reports),
                    "id": f"V{i+1:03d}",
                    "found": False,
                    "rescued": False,
                    "heat_intensity": random.randint(80, 98),
                    "condition": _cond,
                    "triage_priority": CONDITION_TRIAGE[_cond],
                    "notified_rescue": False,
                    "is_mobile": _cond in ("MOBILE_HEALTHY", "MINOR_INJURY"),
                })


class SimulationState:
    def __init__(self, num_victims: int = 0):
        self.zone = DisasterZone(num_victims=num_victims)
        self.base_station = (0, 0)
        base_x, base_y = self.base_station
        # Ensure base cell is not a hazard
        self.zone.hazard_cells[base_y][base_x] = False
        spawn_points = self._sample_accessible_points(NUM_DRONES)
        # Staggered join ticks: ALPHA-1 at tick 0, then one every 4 ticks (~2.8s apart)
        JOIN_TICKS = [0, 4, 7, 10, 13]
        self.drones: Dict[str, Drone] = {}
        for i in range(1, NUM_DRONES + 1):
            start_x, start_y = spawn_points[i - 1]
            drone_id = f"ALPHA-{i}"
            self.drones[drone_id] = Drone(
                id=drone_id,
                x=start_x,
                y=start_y,
                base_x=base_x,
                base_y=base_y,
                status="OFFLINE",
                status_label="OFFLINE",
                is_active=False,
                join_tick=JOIN_TICKS[i - 1],
            )
        self.mission_log: List[Dict] = []
        self.mission_active = False
        self.mission_start_time: Optional[float] = None
        self.mission_end_time: Optional[float] = None
        self.total_victims_found = 0
        self.total_rescued = 0
        self._log_id = 0
        self.tick_count: int = 0                   # Incremented every sim tick
        self._replay_buffer: List[dict] = []
        self.streaming_text: str = ""              # Live LLM token buffer for real-time frontend display
        self.reserved_zones: Dict[str, str] = {}  # zone_id → drone_id that will cover residual
        self.probability_map: List[List[float]] = self._init_probability_map()
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
        self.strategic_brief: dict = {}  # {posture, priority_zones, notes, set_at_tick, expires_at_tick}
        self.brain_mode: str = "AUTO"    # AUTO / CLOUD / EDGE / RULES
        self.brain_active: str = "CLOUD" # current provider in use
        self.leads: List[Lead] = []
        self._lead_counter: int = 0
        self.timeline: list[TimelineEvent] = []
        self._timeline_counter: int = 0
        self._timeline_cap: int = 200

    def _sample_unique_points(self, count: int) -> List[tuple]:
        cells = [(x, y) for y in range(GRID_H) for x in range(GRID_W)]
        selected = random.sample(cells, min(count, len(cells)))
        if len(selected) < count:
            selected.extend(random.choices(cells, k=count - len(selected)))
        return selected

    def _sample_accessible_points(self, count: int) -> List[tuple]:
        cells = self.get_accessible_cells()
        if not cells:
            return self._sample_unique_points(count)
        selected = random.sample(cells, min(count, len(cells)))
        if len(selected) < count:
            selected.extend(random.choices(cells, k=count - len(selected)))
        return selected

    def _init_probability_map(self) -> List[List[float]]:
        """Initialize per-cell survivor probability based on terrain weights."""
        weights: List[List[float]] = []
        total = 0.0
        for y in range(GRID_H):
            row: List[float] = []
            for x in range(GRID_W):
                if self.is_inaccessible(x, y):
                    row.append(0.0)
                else:
                    w = float(TERRAIN_SCAN_WEIGHT.get(self.zone.terrain_types[y][x], 1))
                    row.append(w)
                    total += w
            weights.append(row)
        if total > 0:
            for y in range(GRID_H):
                for x in range(GRID_W):
                    weights[y][x] /= total
        return weights

    def update_probability_after_scan(self, x: int, y: int, survivor_found: bool):
        """Update probability map after scanning a cell."""
        self.probability_map[y][x] = 0.0
        if survivor_found:
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < GRID_W and 0 <= ny < GRID_H
                            and not self.is_inaccessible(nx, ny)
                            and not self.zone.scanned_cells[ny][nx]):
                        dist = max(abs(dx), abs(dy))
                        boost = 0.02 if dist == 1 else 0.01
                        self.probability_map[ny][nx] += boost

    def is_inaccessible(self, x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= GRID_W or y >= GRID_H:
            return True
        return bool(self.zone.hazard_cells[y][x])

    def get_accessible_cells(self) -> List[tuple]:
        return [
            (x, y)
            for y in range(GRID_H)
            for x in range(GRID_W)
            if not self.zone.hazard_cells[y][x]
        ]

    def _distance_to_home(self, drone: Drone) -> int:
        bx, by = self.base_station
        return chebyshev(drone.x, drone.y, bx, by)

    def minimum_battery_to_return(self, drone: Drone) -> float:
        bx, by = self.base_station
        curr_dist = self._distance_to_home(drone)

        # When drone is assigned to a zone but hasn't entered it yet (mid-transit),
        # use the zone's farthest corner distance as the effective return distance.
        # This prevents false RTB triggers during transit — the assignment battery
        # check already validated the drone has sufficient charge for the full mission.
        if drone.assigned_zone_id:
            zone = self.zone.zones.get(drone.assigned_zone_id)
            if zone:
                in_zone = (zone.sx <= drone.x <= zone.ex and zone.sy <= drone.y <= zone.ey)
                if not in_zone:
                    zone_max_dist = max(
                        chebyshev(zone.ex, zone.ey, bx, by),
                        chebyshev(zone.sx, zone.ey, bx, by),
                        chebyshev(zone.ex, zone.sy, bx, by),
                        chebyshev(zone.sx, zone.sy, bx, by),
                    )
                    return (zone_max_dist * BATTERY_DRAIN_MOVE) + BATTERY_RETURN_RESERVE

        return (curr_dist * BATTERY_DRAIN_MOVE) + BATTERY_RETURN_RESERVE

    def should_return_to_base(self, drone: Drone) -> bool:
        if drone.is_charging:
            return False
        return drone.battery <= self.minimum_battery_to_return(drone)

    def append_replay_snapshot(self, events: List[str]) -> None:
        """Store a tick snapshot for replay. Called every 5th tick from server.py."""
        snap: Dict[str, Any] = {
            "tick": self.tick_count,
            "coverage_pct": round(self.metrics.coverage_percent, 1),
            "drones": {
                d_id: {
                    "x": d.x,
                    "y": d.y,
                    "battery": round(d.battery, 1),
                    "status": d.status,
                    "status_label": getattr(d, "status_label", d.status),
                    "returning_to_base": getattr(d, "returning_to_base", False),
                }
                for d_id, d in self.drones.items()
                if d.is_active
            },
            "zones": {
                z_id: z.status.value
                for z_id, z in self.zone.zones.items()
            },
            "events": events,
            "victims": [
                {
                    "x": s["x"],
                    "y": s["y"],
                    "found": s.get("found", False),
                    "rescued": s.get("rescued", False),
                    "is_mobile": s.get("is_mobile", False),
                }
                for s in self.zone.survivors
            ],
            "scanned": [
                [bool(self.zone.scanned_cells[y][x]) for x in range(self.zone.width)]
                for y in range(self.zone.height)
            ],
        }
        # Include static terrain only in the first snapshot to save space
        if not self._replay_buffer:
            snap["terrain"] = [
                [self.zone.terrain_types[y][x] for x in range(self.zone.width)]
                for y in range(self.zone.height)
            ]
        self._replay_buffer.append(snap)

    def get_available_zones(self) -> List[Dict[str, Any]]:
        available = []
        for zid, z in self.zone.zones.items():
            if z.status == ZoneStatus.UNSCANNED:
                area = (z.ex - z.sx + 1) * (z.ey - z.sy + 1)
                zone_score = sum(
                    self.probability_map[y][x]
                    for y in range(z.sy, z.ey + 1)
                    for x in range(z.sx, z.ex + 1)
                    if not self.is_inaccessible(x, y)
                )
                available.append({
                    "zone_id": zid,
                    "sx": z.sx, "sy": z.sy,
                    "ex": z.ex, "ey": z.ey,
                    "scan_cost": area,
                    "zone_score": zone_score,
                })
        return available

    def smart_charge_target(self, drone_id: str) -> float:
        """Returns the minimum battery level needed for the cheapest available zone assignment.
        Drones charge to this level instead of always 100%, saving time at base."""
        available = self.get_available_zones()
        if not available:
            return 100.0  # No zones left — full charge for standby/recall

        base_x, base_y = self.base_station
        min_needed = 100.0

        for z in available:
            transit = min(
                chebyshev(base_x, base_y, z["sx"], z["sy"]),
                chebyshev(base_x, base_y, z["ex"], z["sy"]),
                chebyshev(base_x, base_y, z["sx"], z["ey"]),
                chebyshev(base_x, base_y, z["ex"], z["ey"]),
            )
            zone_obj = self.zone.zones[z["zone_id"]]
            scan_cost = sum(
                1.5 if self.zone.terrain_types[cy][cx] == 'forest' else 1.0
                for cy in range(zone_obj.sy, zone_obj.ey + 1)
                for cx in range(zone_obj.sx, zone_obj.ex + 1)
                if not self.zone.scanned_cells[cy][cx] and not self.is_inaccessible(cx, cy)
            )
            return_cost = max(
                chebyshev(z["ex"], z["ey"], base_x, base_y),
                chebyshev(z["sx"], z["ey"], base_x, base_y),
            )
            total = transit + scan_cost + return_cost + BATTERY_RETURN_RESERVE
            min_needed = min(min_needed, total)

        return min(100.0, min_needed + 10.0)  # +10% safety margin

    def claim_zone(self, zone_id: str, drone_id: str) -> bool:
        zone = self.zone.zones.get(zone_id)
        if not zone:
            return False
        if zone.status != ZoneStatus.UNSCANNED:
            return False
        zone.status = ZoneStatus.IN_PROGRESS
        zone.started_tick = self.tick_count
        zone.assigned_to = drone_id
        return True

    def release_zone(self, zone_id: str):
        zone = self.zone.zones.get(zone_id)
        if zone and zone.status == ZoneStatus.IN_PROGRESS:
            zone.status = ZoneStatus.UNSCANNED
            zone.assigned_to = None

    def _zone_at(self, x: int, y: int) -> Optional[str]:
        """Returns the zone_id containing cell (x, y), or None."""
        for zid, z in self.zone.zones.items():
            if z.sx <= x <= z.ex and z.sy <= y <= z.ey:
                return zid
        return None

    def _get_adjacent_zone_ids(self, zone_id: str) -> List[str]:
        """Returns zone IDs that share a border with the given zone."""
        zone = self.zone.zones.get(zone_id)
        if not zone:
            return []
        adjacent = []
        for zid, z in self.zone.zones.items():
            if zid == zone_id:
                continue
            horiz_touch = (z.sx <= zone.ex + 1 and z.ex >= zone.sx - 1)
            vert_touch = (z.sy <= zone.ey + 1 and z.ey >= zone.sy - 1)
            if horiz_touch and vert_touch:
                adjacent.append(zid)
        return adjacent

    def boost_adjacent_zones(self, found_x: int, found_y: int):
        """After a survivor is found, boost cell probabilities in adjacent unscanned zones."""
        found_zone = self._zone_at(found_x, found_y)
        if not found_zone:
            return
        for zid in self._get_adjacent_zone_ids(found_zone):
            zone = self.zone.zones[zid]
            if zone.status != ZoneStatus.COMPLETE:
                for y in range(zone.sy, zone.ey + 1):
                    for x in range(zone.sx, zone.ex + 1):
                        if not self.zone.scanned_cells[y][x] and not self.is_inaccessible(x, y):
                            self.probability_map[y][x] *= 1.5
                self.log(
                    f"Zone {zid} probability boosted x1.5 "
                    f"(survivor found in adjacent {found_zone})",
                    "INFO",
                )

    def _generate_terrain_priority_path(
        self, zone: 'Zone', start_x: int, start_y: int
    ) -> List[List[int]]:
        """Generate a scan path that visits high-value terrain cells first.
        Groups cells into terrain tiers (city > forest > flat), then within
        each tier uses spatial clustering to minimize backtracking.
        All accessible, unscanned cells are included — full coverage guaranteed."""
        cells_by_tier: Dict[int, List[tuple]] = {7: [], 5: [], 2: [], 1: []}

        for y in range(zone.sy, zone.ey + 1):
            for x in range(zone.sx, zone.ex + 1):
                if self.is_inaccessible(x, y):
                    continue
                if self.zone.scanned_cells[y][x]:
                    continue
                weight = TERRAIN_SCAN_WEIGHT.get(self.zone.terrain_types[y][x], 1)
                cells_by_tier.setdefault(weight, []).append((x, y))

        # Within each tier, sort by proximity to minimize backtracking
        # Use nearest-neighbor greedy ordering
        ordered: List[tuple] = []
        cx, cy = start_x, start_y
        for tier in (7, 5, 2, 1):  # hazard, city, forest, flat
            remaining = list(cells_by_tier[tier])
            while remaining:
                best_idx = 0
                best_dist = chebyshev(cx, cy, remaining[0][0], remaining[0][1])
                for i in range(1, len(remaining)):
                    d = chebyshev(cx, cy, remaining[i][0], remaining[i][1])
                    if d < best_dist:
                        best_dist = d
                        best_idx = i
                cell = remaining.pop(best_idx)
                ordered.append(cell)
                cx, cy = cell

        return [[x, y] for x, y in ordered]

    def assign_zone(self, drone_id: str, zone_id: str) -> Dict[str, Any]:
        """Generates path sequence: transit to closest corner + terrain-priority scan."""
        drone = self.drones.get(drone_id)
        zone = self.zone.zones.get(zone_id)
        if not drone or not zone:
            return {"error": "Drone or Zone not found"}

        start_x, start_y, end_x, end_y = zone.sx, zone.sy, zone.ex, zone.ey

        # Build entire path in a local list first, then assign atomically to avoid
        # a race where the tick loop sees an empty path_queue mid-construction.
        new_queue: List[List[int]] = []

        if zone.residual_path:
            target_sx, target_sy = zone.residual_path[0]
        else:
            corners = [
                (start_x, start_y),
                (end_x, start_y),
                (start_x, end_y),
                (end_x, end_y)
            ]
            best_corner = corners[0]
            min_dist = chebyshev(drone.x, drone.y, corners[0][0], corners[0][1])
            for i in range(1, 4):
                d = chebyshev(drone.x, drone.y, corners[i][0], corners[i][1])
                if d < min_dist:
                    min_dist = d
                    best_corner = corners[i]
            target_sx, target_sy = best_corner

        curr_x, curr_y = drone.x, drone.y

        # Smart transit to zone corner — detours through nearby high-value unscanned cells
        transit = self.compute_smart_transit(curr_x, curr_y, target_sx, target_sy)
        new_queue.extend(transit)
        curr_x, curr_y = target_sx, target_sy

        def enqueue(cell_x: int, cell_y: int) -> None:
            """Append [cell_x, cell_y] to new_queue.
            If the last queued cell is more than 1 step away (gap from skipped cells),
            route through intermediate cells via BFS so the drone never teleports."""
            if not new_queue:
                new_queue.append([cell_x, cell_y])
            else:
                px, py = new_queue[-1]
                if chebyshev(px, py, cell_x, cell_y) > 1:
                    new_queue.extend(self.compute_path(px, py, cell_x, cell_y))
                elif [cell_x, cell_y] != [px, py]:
                    new_queue.append([cell_x, cell_y])

        if zone.residual_path and len(zone.residual_path) > 0:
            # Resume from saved residual, skipping cells already scanned since the diversion
            for cell in zone.residual_path[1:]:
                cx, cy = cell
                if not self.zone.scanned_cells[cy][cx] and not self.is_inaccessible(cx, cy):
                    enqueue(cx, cy)
            zone.residual_path = []
            # Full-zone sweep: catch any cells missed before the diversion started
            for sy in range(start_y, end_y + 1):
                for sx in range(start_x, end_x + 1):
                    if not self.zone.scanned_cells[sy][sx] and not self.is_inaccessible(sx, sy):
                        if [sx, sy] not in new_queue:
                            enqueue(sx, sy)
        else:
            # Terrain-priority path: city cells first, then forest, then flat
            # Nearest-neighbor ordering within each tier minimizes backtracking
            priority_cells = self._generate_terrain_priority_path(
                zone, target_sx, target_sy
            )
            for cell_x, cell_y in priority_cells:
                enqueue(cell_x, cell_y)

        # path_queue is assigned FIRST so the tick loop never sees assigned_zone_id set
        # with an empty queue (which would falsely mark the zone COMPLETE).
        drone.path_queue = new_queue
        drone.assigned_zone_id = zone_id
        drone.status = "ON_MISSION"
        drone.status_label = f"SCANNING {zone_id}"
        drone.scanned_grids = 0

        return {
            "success": True,
            "message": f"Assigned {drone_id} to zone {zone_id} ({start_x},{start_y} -> {end_x},{end_y})"
        }

    def assign_zone_split(
        self, drone_a_id: str, drone_b_id: str, zone_id: str
    ) -> Dict[str, Any]:
        """Split a zone between two drones: drone_a scans top half, drone_b scans bottom half."""
        drone_a = self.drones.get(drone_a_id)
        drone_b = self.drones.get(drone_b_id)
        zone = self.zone.zones.get(zone_id)
        if not drone_a or not drone_b or not zone:
            return {"error": "Drone(s) or Zone not found"}

        mid_y = (zone.sy + zone.ey) // 2

        # Build top-half sub-zone for drone A
        top_zone = Zone(id=zone_id, sx=zone.sx, sy=zone.sy, ex=zone.ex, ey=mid_y)
        top_cells = self._generate_terrain_priority_path(top_zone, drone_a.x, drone_a.y)
        transit_a = self.compute_smart_transit(drone_a.x, drone_a.y, top_zone.sx, top_zone.sy)

        # Build bottom-half sub-zone for drone B
        bot_zone = Zone(id=zone_id, sx=zone.sx, sy=mid_y + 1, ex=zone.ex, ey=zone.ey)
        bot_cells = self._generate_terrain_priority_path(bot_zone, drone_b.x, drone_b.y)
        transit_b = self.compute_smart_transit(drone_b.x, drone_b.y, bot_zone.sx, bot_zone.sy)

        # Build full path queues with gap-fill
        queue_a: List[List[int]] = list(transit_a)
        prev_a: tuple = (transit_a[-1][0], transit_a[-1][1]) if transit_a else (drone_a.x, drone_a.y)
        for cx, cy in top_cells:
            if chebyshev(prev_a[0], prev_a[1], cx, cy) > 1:
                queue_a.extend(self.compute_path(prev_a[0], prev_a[1], cx, cy))
            else:
                queue_a.append([cx, cy])
            prev_a = (cx, cy)

        queue_b: List[List[int]] = list(transit_b)
        prev_b: tuple = (transit_b[-1][0], transit_b[-1][1]) if transit_b else (drone_b.x, drone_b.y)
        for cx, cy in bot_cells:
            if chebyshev(prev_b[0], prev_b[1], cx, cy) > 1:
                queue_b.extend(self.compute_path(prev_b[0], prev_b[1], cx, cy))
            else:
                queue_b.append([cx, cy])
            prev_b = (cx, cy)

        drone_a.path_queue = queue_a
        drone_a.assigned_zone_id = zone_id
        drone_a.status = "ON_MISSION"
        drone_a.status_label = f"SCANNING {zone_id} (TOP)"

        drone_b.path_queue = queue_b
        drone_b.assigned_zone_id = zone_id
        drone_b.status = "ON_MISSION"
        drone_b.status_label = f"SCANNING {zone_id} (BOT)"

        return {
            "success": True,
            "message": f"{drone_a_id} scanning top half, {drone_b_id} scanning bottom half of {zone_id}"
        }

    # ─── Heartbeat Protocol ──────────────────────────────────────────────────────

    def simulate_heartbeats(self) -> None:
        """
        Called every sim tick. Brings drones online in staggered order based on
        join_tick, and marks drones OFFLINE if their battery is completely dead.
        """
        if not self.mission_active:
            return

        for d_id, drone in self.drones.items():
            was_active = drone.is_active

            # Bring drone online when its join tick is reached
            if not drone.is_active and self.tick_count >= drone.join_tick:
                drone.is_active = True
                drone.status = "IDLE"
                drone.status_label = "STANDBY"
                self.log(
                    f"📡 HEARTBEAT: {d_id} joined the swarm mesh network. "
                    f"Battery: {drone.battery:.0f}% | Position: ({drone.x},{drone.y})",
                    "SUCCESS",
                    d_id,
                )

            # Mark drone offline if battery completely dead
            if drone.is_active and drone.battery <= 0:
                drone.is_active = False
                drone.status = "OFFLINE"
                drone.status_label = "OFFLINE (Dead Battery)"
                drone.target_x = None
                drone.target_y = None
                drone.path_queue = []
                self.log(f"🔴 {d_id} lost connection — battery depleted.", "WARN", d_id)

    def simulate_survivor_movement(self) -> None:
        """
        Called every 5 ticks. Unfound mobile survivors (MOBILE_HEALTHY, MINOR_INJURY)
        have a 60% chance to drift to an adjacent non-hazard, unscanned cell.
        Only unfound survivors move — once found they are stationary.
        Survivors only move into unscanned cells so drones can still detect them.
        """
        if not self.mission_active:
            return

        dirs = [(-1,-1),(0,-1),(1,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0)]

        for s in self.zone.survivors:
            if not s.get("is_mobile") or s.get("found") or s["rescued"]:
                continue

            if random.random() > 0.60:
                continue  # 40% chance: stays put this tick

            old_x, old_y = s["x"], s["y"]

            # Only move to adjacent non-hazard, unscanned cells
            candidates = [
                (old_x + dx, old_y + dy)
                for dx, dy in dirs
                if (0 <= old_x + dx < self.zone.width
                    and 0 <= old_y + dy < self.zone.height
                    and not self.zone.hazard_cells[old_y + dy][old_x + dx]
                    and not self.zone.scanned_cells[old_y + dy][old_x + dx])
            ]
            if not candidates:
                continue

            new_x, new_y = random.choice(candidates)
            s["x"], s["y"] = new_x, new_y
            self.log(
                f"🚶 MOBILE SURVIVOR {s['id']} drifted ({old_x},{old_y}) → ({new_x},{new_y})",
                "INFO"
            )

    def _ts(self) -> str:
        mt = self.mission_start_time
        if mt is None:
            return "T+00:00"
        # Freeze at end time once mission is complete
        end = self.mission_end_time if self.mission_end_time else time.time()
        e = int(end - float(mt))
        m, s = divmod(e, 60)
        return f"T+{m:02d}:{s:02d}"

    def log(self, text: str, level: str = "INFO", drone_id: Optional[str] = None):
        self._log_id += 1
        entry = {
            "id": self._log_id,
            "ts": self._ts(),
            "level": level,
            "text": text,
            "drone": drone_id,
        }
        self.mission_log.append(entry)
        tag = f"[{drone_id}]" if drone_id else ""
        import sys
        print(f"[{entry['ts']}][{level}]{tag} {text}", file=sys.stderr, flush=True)

    def generate_thermal_matrix(self, x: int, y: int) -> List[List[int]]:
        matrix = [[random.randint(20, 38) for _ in range(5)] for _ in range(5)]
        if self.zone.hazard_cells[y][x]:
            for row in matrix:
                for ci in range(5):
                    row[ci] = min(100, row[ci] + random.randint(15, 30))
        survivor = next(
            (s for s in self.zone.survivors if s["x"] == x and s["y"] == y and not s["rescued"]),
            None,
        )
        if survivor:
            intensity = survivor["heat_intensity"]
            cx, cy = 2, 2
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    ry, rx = cy + dy, cx + dx
                    if 0 <= ry < 5 and 0 <= rx < 5:
                        dist = math.sqrt(dx**2 + dy**2)
                        heat = int(intensity * math.exp(-0.5 * dist))
                        if heat > matrix[ry][rx]:
                            matrix[ry][rx] = heat
        return matrix

    def add_victim(self, x: int, y: int, report: str, triage: str = "P1-CRITICAL"):
        x = max(0, min(GRID_W - 1, x))
        y = max(0, min(GRID_H - 1, y))
        if self.is_inaccessible(x, y):
            return f"Cannot place victim intel at ({x},{y}) — sector is INACCESSIBLE."
        victim_id = f"V_INTEL_{len(self.zone.survivors) + 1}"
        if any(s['x'] == x and s['y'] == y for s in self.zone.survivors):
            return f"Information received, but sector ({x},{y}) is already marked."
        self.zone.survivors.append({
            "x": x, "y": y,
            "report": report,
            "id": victim_id,
            "found": False,
            "rescued": False,
            "heat_intensity": random.randint(85, 95),
            "condition": "TRAPPED_STABLE",
            "triage_priority": CONDITION_TRIAGE.get(triage, triage),
            "is_mobile": False,
            "notified_rescue": False,
        })
        self.log(f"NEW TARGET INTEL: Victim reported near ({x},{y}) - '{report}'", "INTEL")
        return f"Sector ({x},{y}) added to priority search queue."

    def charge_step(self, drone_id: str) -> str:
        if drone_id not in self.drones:
            return "ERROR: Drone not found"
        drone = self.drones[drone_id]
        drone.base_x, drone.base_y = self.base_station
        if (drone.x, drone.y) != (drone.base_x, drone.base_y):
            return (f"ERROR: {drone_id} must be at base ({drone.base_x},{drone.base_y}). "
                    f"Currently at ({drone.x},{drone.y}).")
        self.metrics.init_drone(drone_id)
        # Track charge events (one increment per charge session start)
        if not drone.is_charging:
            self.metrics.per_drone[drone_id].charges_count += 1
        drone.is_charging = True
        drone.returning_to_base = False
        drone.battery = min(100.0, drone.battery + CHARGE_RATE)
        drone.status = "CHARGING"
        drone.status_label = "CHARGING"
        if drone.battery >= 100.0:
            drone.is_charging = False
            drone.charge_cycles += 1
            drone.status = "IDLE"
            drone.status_label = "READY"
            drone.target_x = None
            drone.target_y = None
            drone.returning_to_base = False
            drone.voice_override = False
            msg = f"[BATTERY] {drone_id} fully charged. Ready for deployment."
            self.log(msg, "CHARGE", drone_id)
        else:
            msg = f"[CHARGING] {drone_id}: {drone.battery:.0f}%"
            self.log(msg, "CHARGE", drone_id)
        return msg

    def scan(self, drone_id: str) -> str:
        if drone_id not in self.drones:
            return "ERROR: Drone not found"
        drone = self.drones[drone_id]
        if drone.battery < BATTERY_DRAIN_SCAN:
            return f"WARNING: {drone_id} critically low battery. Cannot scan."

        drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_SCAN)
        x, y = drone.x, drone.y
        self.zone.scanned_cells[y][x] = True
        # ── Metrics: unique cell count ──────────────────────────────────
        self.metrics.total_cells_scanned = sum(
            1 for sy in range(GRID_H) for sx in range(GRID_W)
            if self.zone.scanned_cells[sy][sx] and not self.zone.hazard_cells[sy][sx]
        )
        self.metrics.init_drone(drone_id)
        self.metrics.per_drone[drone_id].scans_performed += 1
        drone.status_label = "SCANNING"

        matrix = self.generate_thermal_matrix(x, y)
        drone.last_thermal_matrix = matrix

        flat = [v for row in matrix for v in row]
        max_heat = max(flat)
        mean_heat = sum(flat) / len(flat)
        heat_contrast = max_heat - mean_heat
        model_detected = max_heat >= 78 and heat_contrast >= 28
        confidence = min(99, int(max_heat))

        if model_detected:
            survivor = next(
                (s for s in self.zone.survivors
                 if s["x"] == x and s["y"] == y and not s["rescued"]),
                None,
            )
            if survivor and not survivor["found"]:
                survivor["found"] = True
                survivor["found_tick"] = self.tick_count
                survivor["found_by_drone"] = drone_id
                drone.is_waiting_response = True
                drone.victim_report = survivor["report"]
                drone.status = "IDLE"
                drone.status_label = "VICTIM DETECTED"
                self.total_victims_found += 1
                self.metrics.victims_found += 1
                self.metrics.true_positives += 1
                self.boost_adjacent_zones(x, y)  # NEW: dynamic priority update
                self.update_probability_after_scan(x, y, True)
                drone.last_thermal_scan = {
                    "x": x, "y": y,
                    "confidence": confidence,
                    "report": survivor["report"],
                    "triage": survivor["triage_priority"],
                    "condition": survivor.get("condition", "UNKNOWN"),
                }
                if not survivor.get("notified_rescue"):
                    survivor["notified_rescue"] = True
                    self.log(f"📡 RESCUE NOTIFICATION: Victim {survivor['id']} at ({x},{y})", "COMMS")
                msg = (
                    f"[CRITICAL] THERMAL MATCH at ({x},{y})! "
                    f"CNN Confidence: {confidence}% | Triage: {survivor['triage_priority']} | "
                    f"Report: [{survivor['report']}] - DRONE ON STANDBY."
                )
                self.log(msg, "VICTIM_FOUND", drone_id)
                return msg
            elif survivor and survivor["found"] and not survivor["rescued"]:
                self.update_probability_after_scan(x, y, False)
                return f"Confirmed victim at ({x},{y}) — awaiting extraction."
            elif survivor and survivor["rescued"]:
                self.update_probability_after_scan(x, y, False)
                return f"Position ({x},{y}) cleared after successful rescue."

        # Track false positives: thermal triggered but no survivor at this cell
        if model_detected:
            self.metrics.false_positives += 1

        if max_heat > 55:
            self.update_probability_after_scan(x, y, False)
            return (f"Thermal anomaly at ({x},{y}) — heat:{max_heat}, contrast:{heat_contrast:.0f}. NOT human.")
        self.update_probability_after_scan(x, y, False)
        return f"Sector ({x},{y}) clear. Max heat: {max_heat}°C."

    def rescue_victim(self, drone_id: str) -> str:
        drone = self.drones.get(drone_id)
        if not drone:
            return "ERROR: Drone not found"
        for s in self.zone.survivors:
            if (s["x"] == drone.x and s["y"] == drone.y
                    and s["found"] and not s["rescued"]):
                s["rescued"] = True
                s["rescue_tick"] = self.tick_count
                self.total_rescued += 1
                self.metrics.victims_rescued += 1
                drone.is_waiting_response = False
                drone.victim_report = None
                drone.status = "IDLE"
                drone.status_label = "RESUMING"
                msg = (f"[SUCCESS] Survivor {s['id']} extracted from ({drone.x},{drone.y}). "
                       f"Total rescued: {self.total_rescued}")
                self.log(msg, "SUCCESS", drone_id)
                return msg
        return f"No unrescued victim at ({drone.x},{drone.y})."

    def guide_victim(self, drone_id: str) -> str:
        drone = self.drones.get(drone_id)
        if not drone: return "Drone not found"
        for s in self.zone.survivors:
            if s["x"] == drone.x and s["y"] == drone.y and s["found"] and not s["rescued"]:
                if s.get("is_mobile"):
                    drone.is_guiding = True
                    drone.guiding_victim_id = s["id"]
                    drone.target_x, drone.target_y = drone.base_x, drone.base_y
                    drone.is_waiting_response = False
                    drone.status = "RETURNING"
                    drone.status_label = "GUIDING TO BASE"
                    self.log(f"Drone {drone_id} guiding survivor {s['id']} to safety zone.", "INFO", drone_id)
                    return f"Guiding survivor {s['id']} to ({drone.base_x},{drone.base_y})."
                else:
                    return f"Survivor {s['id']} is unable to move. Stationary rescue required."
        return "No victim at current location."

    def get_estimated_finish_time(self) -> str:
        unscanned = len(self.get_unscanned_cells())
        active_drones = len([d for d in self.drones.values() if d.status_label != "STANDBY"])
        if active_drones == 0: return "NA"
        seconds = (unscanned / active_drones) * 1.5 * 0.7
        m, s = divmod(int(seconds), 60)
        return f"{m:02}m {s:02}s"

    def compute_path(self, x0: int, y0: int, x1: int, y1: int) -> List[List[int]]:
        """BFS shortest path from (x0,y0) to (x1,y1) using 8-directional movement,
        avoiding hazard/lake cells. Used for all direct movement (RTB, voice dispatch)
        so drones never cut through lake terrain."""
        if x0 == x1 and y0 == y1:
            return []
        from collections import deque
        visited: set = {(x0, y0)}
        queue: deque = deque([(x0, y0, [])])
        while queue:
            cx, cy, path = queue.popleft()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if (nx, ny) in visited:
                        continue
                    if nx < 0 or ny < 0 or nx >= GRID_W or ny >= GRID_H:
                        continue
                    # Block hazard cells except the destination (base is always clear)
                    if self.zone.hazard_cells[ny][nx] and not (nx == x1 and ny == y1):
                        continue
                    new_path = path + [[nx, ny]]
                    if nx == x1 and ny == y1:
                        return new_path
                    visited.add((nx, ny))
                    queue.append((nx, ny, new_path))
        # Fallback: direct step (grid should always be connected via non-lake cells)
        return [[x1, y1]]

    def compute_smart_transit(
        self, x0: int, y0: int, x1: int, y1: int, max_detour: int = 3
    ) -> List[List[int]]:
        """BFS transit that detours through nearby unscanned city/forest cells
        when the detour cost is within max_detour extra steps.
        Returns a path from (x0,y0) to (x1,y1) — possibly longer than shortest."""
        base_path = self.compute_path(x0, y0, x1, y1)
        base_cost = len(base_path)
        if base_cost == 0:
            return base_path

        # Collect unscanned high-value cells near the base path
        path_set = set((c[0], c[1]) for c in base_path)
        path_set.add((x0, y0))
        candidates: List[tuple] = []
        for px, py in path_set:
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    nx, ny = px + dx, py + dy
                    if (0 <= nx < GRID_W and 0 <= ny < GRID_H
                            and not self.zone.scanned_cells[ny][nx]
                            and not self.is_inaccessible(nx, ny)
                            and (nx, ny) not in path_set
                            and self.zone.terrain_types[ny][nx] in ('hazard', 'city', 'forest')):
                        candidates.append((nx, ny))

        if not candidates:
            return base_path

        # Score candidates by terrain value, pick best one within detour budget
        candidates.sort(
            key=lambda c: -TERRAIN_SCAN_WEIGHT.get(self.zone.terrain_types[c[1]][c[0]], 1)
        )

        for cx, cy in candidates[:5]:  # Try top 5 candidates
            leg_a = self.compute_path(x0, y0, cx, cy)
            leg_b = self.compute_path(cx, cy, x1, y1)
            detour_cost = len(leg_a) + len(leg_b)
            if detour_cost <= base_cost + max_detour:
                return leg_a + leg_b

        return base_path

    def get_unscanned_cells(self) -> List[List[int]]:
        return [
            [x, y]
            for y in range(GRID_H)
            for x in range(GRID_W)
            if not self.zone.scanned_cells[y][x] and not self.zone.hazard_cells[y][x]
        ]

    def get_nearby_unscanned_cells(self, x: int, y: int, radius: int = 6) -> List[List[int]]:
        """Returns unscanned, accessible cells within Chebyshev radius, sorted by distance."""
        candidates = []
        for cy in range(max(0, y - radius), min(self.zone.height, y + radius + 1)):
            for cx in range(max(0, x - radius), min(self.zone.width, x + radius + 1)):
                if not self.zone.scanned_cells[cy][cx] and not self.is_inaccessible(cx, cy):
                    dist = chebyshev(x, y, cx, cy)
                    candidates.append((dist, [cx, cy]))
        candidates.sort(key=lambda c: c[0])
        return [c[1] for c in candidates]

    def get_status(self) -> Dict[str, Any]:
        scanned = sum(
            1
            for y in range(GRID_H)
            for x in range(GRID_W)
            if self.zone.scanned_cells[y][x] and not self.zone.hazard_cells[y][x]
        )
        accessible_total = sum(
            1
            for y in range(GRID_H)
            for x in range(GRID_W)
            if not self.zone.hazard_cells[y][x]
        )
        coverage = 100.0 if accessible_total == 0 else float(round((scanned / accessible_total) * 100))

        # Enrich zones with `score` + `terrain_counts` so the Commander LLM can
        # distinguish hazard/city/forest/flat zones in its prompt. Without this,
        # _format_state() falls back to score=0/terrain={} and the Commander
        # assigns uniform priorities (see docs/search-strategy-regressions.md §3).
        zone_payload = self.zone.model_dump()
        zones_out = zone_payload.get("zones", {})
        for zid, z in self.zone.zones.items():
            if zid not in zones_out:
                continue
            score = sum(
                self.probability_map[y][x]
                for y in range(z.sy, z.ey + 1)
                for x in range(z.sx, z.ex + 1)
                if not self.is_inaccessible(x, y)
                and not self.zone.scanned_cells[y][x]
            )
            terrain_counts: Dict[str, int] = {}
            for y in range(z.sy, z.ey + 1):
                for x in range(z.sx, z.ex + 1):
                    t = self.zone.terrain_types[y][x]
                    terrain_counts[t] = terrain_counts.get(t, 0) + 1
            zones_out[zid]["score"] = round(score, 3)
            zones_out[zid]["terrain_counts"] = terrain_counts

        return {
            "drones": [d.model_dump() for d in self.drones.values()],
            "zone": zone_payload,
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
                "elapsed_sec": round(time.time() - self.mission_start_time, 1) if self.mission_start_time and self.mission_active else 0,
                "eta_ts": self.get_estimated_finish_time(),
                "grid_w": GRID_W,
                "grid_h": GRID_H,
            },
            "metrics": self.metrics.to_dict(),
            "brain": {
                "mode": self.brain_mode,
                "active": self.brain_active,
            },
            "leads": [
                {
                    "id": l.id, "tick": l.tick, "lang": l.lang,
                    "raw": l.raw, "english": l.english,
                    "x": l.x, "y": l.y,
                    "urgency": l.urgency, "status": l.status,
                }
                for l in self.leads
            ],
            "timeline": [
                {
                    "id": e.id, "tick": e.tick, "ts": e.ts,
                    "kind": e.kind, "brain": e.brain,
                    "duration_ms": e.duration_ms, "payload": e.payload,
                }
                for e in self.timeline[-200:]
            ],
        }

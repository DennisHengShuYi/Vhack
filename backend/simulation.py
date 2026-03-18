"""
Disaster Zone Simulation — 20×15 grid with survivor thermal scanning.
This is the core simulation that the MCP tools control.
"""
import random
import time
import math
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from drone import DroneStatus

# ─── Grid Constants ────────────────────────────────────────────────────────────
GRID_W               = 20
GRID_H               = 15
CHARGE_RATE          = 34.0   # % per charge_step call
BATTERY_DRAIN_MOVE   = 1.0    # % per cell moved
BATTERY_DRAIN_SCAN   = 1.0    # % per thermal scan
LOW_BATTERY_THRESHOLD = 25.0  # % — recall threshold
BATTERY_RETURN_RESERVE = 8.0  # % — emergency reserve after reaching base
NUM_DRONES           = 5

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
    priority: str = "MEDIUM"
    residual_path: List[List[int]] = []

def chebyshev(x1: int, y1: int, x2: int, y2: int) -> int:
    return max(abs(x2 - x1), abs(y2 - y1))

class Drone(BaseModel):
    id: str
    x: int = 0
    y: int = 0
    base_x: int = 0
    base_y: int = 0
    battery: float = 0.0
    is_charging: bool = False
    is_waiting_response: bool = False
    returning_to_base: bool = False
    mission_complete_rtb: bool = False
    status: DroneStatus = DroneStatus.IDLE
    is_connected: bool = False
    has_pinged: bool = False
    target_x: Optional[int] = None
    target_y: Optional[int] = None
    victim_report: Optional[str] = None
    last_thermal_matrix: Optional[List[List[int]]] = None
    last_thermal_scan: Optional[Dict[str, Any]] = None
    charge_cycles: int = 0
    status_label: str = "STANDBY"
    path_history: List[List[int]] = []
    is_guiding: bool = False
    guiding_victim_id: Optional[str] = None
    voice_override: bool = False
    original_pos: Optional[List[int]] = None
    path_queue: List[List[int]] = []
    scanned_grids: int = 0
    assigned_zone_id: Optional[str] = None


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
            for _ in range(20):
                hx, hy = random.randint(1, self.width - 2), random.randint(1, self.height - 2)
                self.hazard_cells[hy][hx] = True

        if not self.terrain_types:
            self.terrain_types = [['flat'] * self.width for _ in range(self.height)]
            for _ in range(12):
                mx, my = random.randint(2, self.width - 3), random.randint(2, self.height - 3)
                self.terrain_types[my][mx] = 'mountain'
            for _ in range(8):
                lx, ly = random.randint(1, self.width - 2), random.randint(1, self.height - 2)
                self.terrain_types[ly][lx] = 'lake'

        if not self.zones:
            # 12 zones: 4 columns × 3 rows of 5×5 cells each
            self.zones = {
                "Z0":  Zone(id="Z0",  sx=0,  sy=0,  ex=4,  ey=4,  priority="HIGH"),
                "Z1":  Zone(id="Z1",  sx=5,  sy=0,  ex=9,  ey=4),
                "Z2":  Zone(id="Z2",  sx=10, sy=0,  ex=14, ey=4),
                "Z3":  Zone(id="Z3",  sx=15, sy=0,  ex=19, ey=4),
                "Z4":  Zone(id="Z4",  sx=0,  sy=5,  ex=4,  ey=9),
                "Z5":  Zone(id="Z5",  sx=5,  sy=5,  ex=9,  ey=9,  priority="HIGH"),
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
            placed = set()
            for i in range(num):
                while True:
                    sx = random.randint(1, self.width - 1)
                    sy = random.randint(1, self.height - 1)
                    if (sx, sy) not in placed:
                        placed.add((sx, sy))
                        break
                self.survivors.append({
                    "x": sx, "y": sy,
                    "report": random.choice(reports),
                    "id": f"V{i+1:03d}",
                    "found": False,
                    "rescued": False,
                    "heat_intensity": random.randint(80, 98),
                    "triage_priority": random.choice(["P1-CRITICAL", "P2-URGENT", "P3-STABLE"]),
                    "can_move": random.choice([True, False, False]),
                    "notified_rescue": False,
                })


class SimulationState:
    def __init__(self, num_victims: int = 0):
        self.zone = DisasterZone(num_victims=num_victims)
        self.base_station = (0, 0)
        base_x, base_y = self.base_station
        # Ensure base cell is not a hazard
        self.zone.hazard_cells[base_y][base_x] = False
        spawn_points = self._sample_accessible_points(NUM_DRONES)
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
                status=DroneStatus.IDLE,
                status_label="UNAVAILABLE",
                is_connected=False,
                has_pinged=False,
            )
        self.mission_log: List[Dict] = []
        self.mission_active = False
        self.mission_start_time: Optional[float] = None
        self.total_victims_found = 0
        self.total_rescued = 0
        self._log_id = 0
        self.pending_intel: List[Dict] = []

    def simulate_heartbeats(self):
        """Randomly simulation of receiving discovery heartbeats from drones."""
        for d_id, drone in self.drones.items():
            if not drone.is_connected:
                # 20% chance to establish/restore link
                if random.random() < 0.20:
                    if not drone.has_pinged:
                        # First time initialization
                        drone.has_pinged = True
                        drone.battery = random.uniform(35.0, 100.0)
                        self.log(f"🔋 [INIT] {d_id} established first link. Battery: {drone.battery:.0f}%", "INFO", d_id)
                    else:
                        self.log(f"📡 [RESTORED] {d_id} reconnected to mesh network.", "SUCCESS", d_id)
                    
                    drone.is_connected = True
                    if drone.battery < LOW_BATTERY_THRESHOLD:
                        drone.status_label = "NEEDS CHARGE"
                    else:
                        drone.status_label = "AWAITING ORDERS"
                else:
                    drone.status_label = "UNAVAILABLE"
                    drone.status = DroneStatus.IDLE

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
        return abs(drone.x - bx) + abs(drone.y - by)

    def minimum_battery_to_return(self, drone: Drone) -> float:
        return (self._distance_to_home(drone) * BATTERY_DRAIN_MOVE) + BATTERY_RETURN_RESERVE

    def should_return_to_base(self, drone: Drone) -> bool:
        if drone.is_charging:
            return False
        low_threshold = drone.battery < LOW_BATTERY_THRESHOLD
        cannot_safely_return_later = drone.battery <= self.minimum_battery_to_return(drone)
        return low_threshold or cannot_safely_return_later

    def is_zone_fully_scanned(self, zone_id: str) -> bool:
        zone = self.zone.zones.get(zone_id)
        if not zone: return True
        for y in range(zone.sy, zone.ey + 1):
            for x in range(zone.sx, zone.ex + 1):
                if not self.zone.scanned_cells[y][x]:
                    return False
        return True
    
    def get_available_zones(self) -> List[Dict[str, Any]]:
        available = []
        for zid, z in self.zone.zones.items():
            if z.status == ZoneStatus.UNSCANNED:
                # Optimized cost: use residual path length if it exists, else full area
                cost = len(z.residual_path) if z.residual_path else (z.ex - z.sx + 1) * (z.ey - z.sy + 1)
                
                # Optimized transit: if it is a residual handoff, fly to where the last drone left off
                tsx, tsy = z.sx, z.sy
                label_suffix = ""
                if z.residual_path and len(z.residual_path) > 0:
                    tsx, tsy = z.residual_path[0]
                    label_suffix = " (RESIDUAL HANDOFF)"

                available.append({
                    "zone_id": zid + label_suffix,
                    "sx": tsx, "sy": tsy,
                    "ex": z.ex, "ey": z.ey,
                    "scan_cost": cost,
                    "priority": z.priority,
                    "real_zid": zid
                })
        return available

    def claim_zone(self, zone_id: str, drone_id: str) -> bool:
        zone = self.zone.zones.get(zone_id)
        if not zone:
            return False
        if zone.status != ZoneStatus.UNSCANNED:
            return False
        zone.status = ZoneStatus.IN_PROGRESS
        zone.assigned_to = drone_id
        return True

    def release_zone(self, zone_id: str):
        zone = self.zone.zones.get(zone_id)
        if zone and zone.status == ZoneStatus.IN_PROGRESS:
            zone.status = ZoneStatus.UNSCANNED
            zone.assigned_to = None

    def assign_zone(self, drone_id: str, zone_id: str) -> Dict[str, Any]:
        """Generates path sequence: transit to closest corner + zig-zag scan."""
        drone = self.drones.get(drone_id)
        zone = self.zone.zones.get(zone_id)
        if not drone or not zone:
            return {"error": "Drone or Zone not found"}

        temp_path = []
        start_x, start_y, end_x, end_y = zone.sx, zone.sy, zone.ex, zone.ey

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
        if (curr_x, curr_y) == (target_sx, target_sy):
            temp_path.append([curr_x, curr_y])

        while (curr_x, curr_y) != (target_sx, target_sy):
            if curr_x < target_sx: curr_x += 1
            elif curr_x > target_sx: curr_x -= 1
            if curr_y < target_sy: curr_y += 1
            elif curr_y > target_sy: curr_y -= 1
            temp_path.append([curr_x, curr_y])

        if zone.residual_path and len(zone.residual_path) > 0:
            for i in range(1, len(zone.residual_path)):
                temp_path.append(zone.residual_path[i])
            zone.residual_path = []
        else:
            rev_x = (target_sx == end_x)
            rev_y = (target_sy == end_y)
            y_range = range(start_y, end_y + 1)
            if rev_y:
                y_range = range(end_y, start_y - 1, -1)
 
            # --- NEW: Strategic Priority Scanning ---
            # Separate cells by priority (Flat first, Terrain/Hazards last)
            flat_priority = []
            low_priority = []

            for i, y in enumerate(y_range):
                if i % 2 == 0:
                    xs = range(end_x, start_x - 1, -1) if rev_x else range(start_x, end_x + 1)
                else:
                    xs = range(start_x, end_x + 1) if rev_x else range(end_x, start_x - 1, -1)
                for x in xs:
                    terrain = self.zone.terrain_types[y][x]
                    is_hazard = self.zone.hazard_cells[y][x]
                    # Anything not 'flat' or marked as a 'hazard' gets pushed to the end of the queue
                    if terrain == 'flat' and not is_hazard:
                        flat_priority.append([x, y])
                    else:
                        low_priority.append([x, y])
            
            # Assemble: Transit -> Flat Surface Scan -> Tactical Environment Scan (Mountains/Lakes/Hazards)
            for cell in flat_priority:
                if not temp_path or temp_path[-1] != cell:
                    temp_path.append(cell)
            for cell in low_priority:
                if not temp_path or temp_path[-1] != cell:
                    temp_path.append(cell)

        # ATOMIC ASSIGNMENT: Update state at the very end to prevent Loop A race conditions
        drone.assigned_zone_id = zone_id
        drone.path_queue = temp_path
        drone.status = "ON_MISSION"
        drone.status_label = f"SCANNING {zone_id}"
        drone.scanned_grids = 0
        drone.returning_to_base = False
        drone.is_charging = False
        drone.is_waiting_response = False
        drone.mission_complete_rtb = False
        drone.target_x = None
        drone.target_y = None

        return {
            "success": True,
            "message": f"Assigned {drone_id} to zone {zone_id} ({start_x},{start_y} -> {end_x},{end_y})"
        }

    def _ts(self) -> str:
        mt = self.mission_start_time
        if mt is None:
            return "T+00:00"
        e = int(time.time() - float(mt))
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
            "triage_priority": triage
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
                drone.is_waiting_response = True
                drone.victim_report = survivor["report"]
                drone.status = "IDLE"
                drone.status_label = "VICTIM DETECTED"
                self.total_victims_found += 1
                drone.last_thermal_scan = {
                    "x": x, "y": y,
                    "confidence": confidence,
                    "report": survivor["report"],
                    "triage": survivor["triage_priority"],
                }
                if not survivor.get("notified_rescue"):
                    survivor["notified_rescue"] = True
                    self.log(f"📡 RESCUE NOTIFICATION: Victim {survivor['id']} at ({x},{y})", "COMMS")
                msg = (
                    f"[CRITICAL] THERMAL MATCH at ({x},{y})! "
                    f"CNN Confidence: {confidence}% | Triage: {survivor['triage_priority']} | "
                    f"Report: [{survivor['report']}] - DRONE ON STANDBY."
                )
                if survivor.get("can_move"):
                    msg += " [SURVIVOR ABLE TO MOVE - CAN BE GUIDED TO BASE]"
                self.log(msg, "VICTIM_FOUND", drone_id)
                return msg
            elif survivor and survivor["found"] and not survivor["rescued"]:
                return f"Confirmed victim at ({x},{y}) — awaiting extraction."
            elif survivor and survivor["rescued"]:
                return f"Position ({x},{y}) cleared after successful rescue."

        if max_heat > 55:
            return (f"Thermal anomaly at ({x},{y}) — heat:{max_heat}°, contrast:{heat_contrast:.0f}. NOT human.")
        return f"Sector ({x},{y}) clear. Max heat: {max_heat}°C."

    def rescue_victim(self, drone_id: str) -> str:
        drone = self.drones.get(drone_id)
        if not drone:
            return "ERROR: Drone not found"
        for s in self.zone.survivors:
            if (s["x"] == drone.x and s["y"] == drone.y
                    and s["found"] and not s["rescued"]):
                s["rescued"] = True
                self.total_rescued += 1
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
                if s.get("can_move"):
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

    def get_unscanned_cells(self) -> List[List[int]]:
        return [
            [x, y]
            for y in range(GRID_H)
            for x in range(GRID_W)
            if not self.zone.scanned_cells[y][x] and not self.zone.hazard_cells[y][x]
        ]

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
        return {
            "drones": [d.model_dump() for d in self.drones.values()],
            "zone": self.zone.model_dump(),
            "log": self.mission_log,
            "base_station": {"x": self.base_station[0], "y": self.base_station[1]},
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
        }

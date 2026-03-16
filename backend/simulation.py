"""
Disaster Zone Simulation — 10×10 grid with survivor thermal scanning.
This is the core simulation that the MCP tools control.
"""
import random
import time
import math
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

# ─── Grid Constants ────────────────────────────────────────────────────────────
GRID_W               = 10
GRID_H               = 10
CHARGE_RATE          = 100.0 / (60.0 / 0.7)   # % per charge_step call (60s total)
BATTERY_DRAIN_MOVE   = 2.0    # % per cell moved (increased for fast demo drain)
BATTERY_DRAIN_SCAN   = 1.0    # % per thermal scan
LOW_BATTERY_THRESHOLD = 25.0  # % — recall threshold
NUM_DRONES           = 5


class Drone(BaseModel):
    id: str
    x: int = 0
    y: int = 0
    battery: Optional[float] = None  # None = UNKNOWN
    is_active: bool = False  # Starts offline until first heartbeat
    is_charging: bool = False
    is_waiting_response: bool = False
    returning_to_base: bool = False
    mission_complete_rtb: bool = False
    target_x: Optional[int] = None
    target_y: Optional[int] = None
    victim_report: Optional[str] = None
    last_thermal_matrix: Optional[List[List[int]]] = None
    last_thermal_scan: Optional[Dict[str, Any]] = None
    charge_cycles: int = 0
    status_label: str = "UNKNOWN"
    path_history: List[List[int]] = []  # recent positions for trail
    is_guiding: bool = False
    guiding_victim_id: Optional[str] = None
    voice_override: bool = False # If true, AI planning won't overwrite target
    original_pos: Optional[List[int]] = None # Where to return after voice command


class DisasterZone(BaseModel):
    width: int = GRID_W
    height: int = GRID_H
    survivors: List[Dict[str, Any]] = []
    scanned_cells: List[List[bool]] = []
    hazard_cells: List[List[bool]] = []   # collapsed structures / fire
    terrain_types: List[List[str]] = []   # 'flat', 'mountain', 'lake'

    def __init__(self, **data):
        super().__init__(**data)
        if not self.scanned_cells:
            self.scanned_cells = [[False] * self.width for _ in range(self.height)]
        if not self.hazard_cells:
            # Scatter some hazard zones
            self.hazard_cells = [[False] * self.width for _ in range(self.height)]
            for _ in range(8):
                hx, hy = random.randint(1, 9), random.randint(1, 9)
                self.hazard_cells[hy][hx] = True
        
        if not self.terrain_types:
            self.terrain_types = [['flat'] * self.width for _ in range(self.height)]
            # Add mountains and lakes
            for _ in range(5):
                mx, my = random.randint(2, 8), random.randint(2, 8)
                self.terrain_types[my][mx] = 'mountain'
            for _ in range(3):
                lx, ly = random.randint(1, 8), random.randint(1, 8)
                self.terrain_types[ly][lx] = 'lake'

        if not self.survivors:
            num = random.randint(5, 8)
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
                    "can_move": random.choice([True, False, False]), # 1 in 3 can walk
                    "notified_rescue": False,
                })


class SimulationState:
    def __init__(self):
        self.drones: Dict[str, Drone] = {
            f"ALPHA-{i}": Drone(id=f"ALPHA-{i}", x=0, y=0, status_label="STANDBY")
            for i in range(1, NUM_DRONES + 1)
        }
        self.zone = DisasterZone()
        self.mission_log: List[Dict] = []
        self.base_station = (0, 0)
        self.mission_active = False
        self.mission_start_time: Optional[float] = None
        self.total_victims_found = 0
        self.total_rescued = 0
        self._log_id = 0

    # ─── Heartbeat Simulation ────────────────────────────────────────────────
    
    def simulate_heartbeats(self) -> List[str]:
        """Runs every tick to randomly connect/disconnect drones from the mesh network."""
        if not self.mission_active:
            return list(self.drones.keys())
            
        active_drones = []
        for d_id, drone in self.drones.items():
            was_active = drone.is_active
            
            # Simulate a continuous connection state machine
            is_active_now = False
            
            if was_active:
                # Prototype rule: Drones do not randomly drop connection once established
                is_active_now = True
            else:
                # If they have never connected before, give them a high 60% chance to join immediately
                if drone.battery is None:
                    is_active_now = random.random() < 0.20
                else:
                    # 20% chance per tick to regain a dropped connection later in the mission
                    is_active_now = random.random() < 0.20
                
            # If this is the drone's first time connecting, randomize its battery
            if is_active_now and drone.battery is None:
                drone.battery = random.uniform(0.0, 100.0)
                self.log(f"🔋 [INIT] {d_id} established first link. Battery pinged: {drone.battery:.0f}%", "INFO", d_id)
                
            # Has power check (must be assigned by now if active)
            has_power = drone.battery is not None and drone.battery >= 10.0
            
            if not has_power:
                is_active_now = False
            
            drone.is_active = is_active_now
            
            if is_active_now:
                active_drones.append(d_id)
                
            if not is_active_now:
                if was_active:
                    self.log(f"⚠️ [CONNECTION LOST] {d_id} dropped from mesh network" + (" (LOW BATTERY)" if not has_power else ""), "WARN", d_id)
                if not has_power:
                    drone.status_label = "OFFLINE (Low Battery)"
                else:
                    drone.status_label = "OFFLINE (No Signal)"
            elif not was_active and is_active_now:
                # Just came back online
                self.log(f"✅ [DETECTED / RECONNECTED] {d_id} joined the swarm mesh network.", "SUCCESS", d_id)
                if drone.battery is not None and drone.battery < LOW_BATTERY_THRESHOLD:
                    drone.status_label = "NEEDS CHARGE" # Battery low, needs to RTB
                elif drone.is_charging:
                    drone.status_label = "CHARGING"
                else:
                    drone.status_label = "STANDBY"
                    
            # Reset target if disconnected so they don't ghost move
            if not drone.is_active:
                drone.target_x = None
                drone.target_y = None
                
        # Calculate exactly who is dropped
        all_drone_ids = list(self.drones.keys())
        dropped = set(all_drone_ids) - set(active_drones)
        
        # Explicit print for the user's terminal
        print(f"[{self._ts()}] 📡 --- HEARTBEAT CHECK ---")
        if active_drones:
            print(f"[{self._ts()}] 🟢 Drones AVAILABLE: {', '.join(active_drones)}")
        if dropped:
            print(f"[{self._ts()}] 🔴 Drones UNAVAILABLE: {', '.join(dropped)}")
            
        return active_drones

    # ─── Utilities ───────────────────────────────────────────────────────────

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
        print(f"[{entry['ts']}][{level}]{tag} {text}")

    # ─── Thermal Sensing ─────────────────────────────────────────────────────

    def generate_thermal_matrix(self, x: int, y: int) -> List[List[int]]:
        """Generate a realistic 5×5 thermal sensor matrix with Gaussian heat bloom for survivors."""
        matrix = [[random.randint(20, 38) for _ in range(5)] for _ in range(5)]

        # Check for fire / hazard — adds broad heat noise
        if self.zone.hazard_cells[y][x]:
            for row in matrix:
                for ci in range(5):
                    row[ci] = min(100, row[ci] + random.randint(15, 30))

        # Survivor heat signature (Gaussian bloom centered at [2,2])
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

    # ─── MCP Tool Implementations ────────────────────────────────────────────

    def move_drone(self, drone_id: str, x: int, y: int) -> str:
        """Move drone directly to (x,y). Used by LLM for strategic positioning."""
        if drone_id not in self.drones:
            return f"ERROR: '{drone_id}' not found. Use list_drones() first."
        drone = self.drones[drone_id]
        if drone.is_waiting_response:
            return f"{drone_id} is on VICTIM STANDBY — awaiting operator confirmation."
        if not drone.is_active:
            return f"{drone_id} is OFFLINE (No heartbeat). Cannot execute move command."
            
        x = max(0, min(GRID_W - 1, x))
        y = max(0, min(GRID_H - 1, y))

        steps = abs(drone.x - x) + abs(drone.y - y)
        cost = steps * BATTERY_DRAIN_MOVE
        if drone.battery < cost + 5:
            return (f"WARNING: Insufficient battery ({drone.battery:.0f}%) for "
                    f"{steps}-cell move (costs {cost:.0f}%). Recall to (0,0) first.")

        old_x, old_y = drone.x, drone.y
        drone.x, drone.y = x, y
        drone.battery = max(0.0, drone.battery - cost)
        drone.target_x, drone.target_y = x, y
        drone.status_label = "NAVIGATING"
        
        # If guiding a survivor, they move with the drone
        if drone.is_guiding and drone.guiding_victim_id:
             for s in self.zone.survivors:
                 if s["id"] == drone.guiding_victim_id:
                     s["x"], s["y"] = x, y
                     if (x, y) == (0, 0):
                         s["rescued"] = True
                         drone.is_guiding = False
                         drone.guiding_victim_id = None
                         self.total_rescued += 1
                         self.log(f"Survivor {s['id']} guided safely to base station!", "SUCCESS", drone_id)

        drone.path_history.append([x, y])
        while len(drone.path_history) > 15:
            drone.path_history.pop(0)
        msg = f"Moved {drone_id} ({old_x},{old_y})→({x},{y}) | Battery: {drone.battery:.0f}%"
        self.log(msg, "MOVE", drone_id)
        return msg

    def add_victim(self, x: int, y: int, report: str, triage: str = "P1-CRITICAL"):
        """Dynamically add a new victim to the simulation (e.g. from intelligence)."""
        x = max(0, min(GRID_W - 1, x))
        y = max(0, min(GRID_H - 1, y))
        victim_id = f"V_INTEL_{len(self.zone.survivors) + 1}"
        
        # Check if a victim already exists at this spot to avoid duplicates
        if any(s['x'] == x and s['y'] == y for s in self.zone.survivors):
            return f"Information received, but sector ({x},{y}) is already marked."

        self.zone.survivors.append({
            "x": x, "y": y,
            "report": report,
            "id": victim_id,
            "found": False,   # Needs scanning to confirm
            "rescued": False,
            "heat_intensity": random.randint(85, 95),
            "triage_priority": triage
        })
        self.log(f"NEW TARGET INTEL: Victim reported near ({x},{y}) - '{report}'", "INTEL")
        return f"Sector ({x},{y}) added to priority search queue."

    def charge_step(self, drone_id: str) -> str:
        """Charge drone 25% per call. Must be at base (0,0)."""
        if drone_id not in self.drones:
            return "ERROR: Drone not found"
        drone = self.drones[drone_id]
        if not drone.is_active:
            return f"ERROR: {drone_id} is OFFLINE."
        if (drone.x, drone.y) != self.base_station:
            return (f"ERROR: {drone_id} must be at base (0,0). "
                    f"Currently at ({drone.x},{drone.y}). Move to (0,0) first.")
        drone.is_charging = True
        drone.returning_to_base = False
        drone.battery = min(100.0, drone.battery + CHARGE_RATE)
        drone.status_label = f"CHARGING ({drone.battery:.0f}%)"
        if drone.battery >= 100.0:
            drone.is_charging = False
            drone.charge_cycles += 1
            drone.status_label = "READY"
            msg = f"[BATTERY] {drone_id} fully charged. Ready for deployment. Cycles: {drone.charge_cycles}"
            self.log(msg, "CHARGE", drone_id)
        else:
            msg = f"[CHARGING] {drone_id}: {drone.battery:.0f}%"
            # self.log(msg, "CHARGE", drone_id) # Prevent terminal spam every 0.7s during 60s charge
        return msg

    def scan(self, drone_id: str) -> str:
        """Execute thermal scan at drone's current position."""
        if drone_id not in self.drones:
            return "ERROR: Drone not found"
        drone = self.drones[drone_id]
        if not drone.is_active:
            return f"WARNING: {drone_id} is OFFLINE. Cannot scan."
        if drone.battery < BATTERY_DRAIN_SCAN:
            return f"WARNING: {drone_id} critically low battery. Cannot scan."

        drone.battery = max(0.0, drone.battery - BATTERY_DRAIN_SCAN)
        x, y = drone.x, drone.y
        self.zone.scanned_cells[y][x] = True
        drone.status_label = "SCANNING"

        # Generate thermal reading
        matrix = self.generate_thermal_matrix(x, y)
        drone.last_thermal_matrix = matrix

        # CNN-simulated inference via heat statistics
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
                drone.status_label = "VICTIM DETECTED"
                self.total_victims_found += 1
                drone.last_thermal_scan = {
                    "x": x, "y": y,
                    "confidence": confidence,
                    "report": survivor["report"],
                    "triage": survivor["triage_priority"],
                }
                if not survivor["notified_rescue"]:
                    survivor["notified_rescue"] = True
                    self.log(f"📡 NOTIFICATION SENT TO RESCUE TEAM: Victim {survivor['id']} at ({x},{y})", "COMMS")

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
            return (f"Thermal anomaly at ({x},{y}) — heat:{max_heat}°, "
                    f"contrast:{heat_contrast:.0f}. NOT human (debris/fire). Coverage updated.")
        return (f"Sector ({x},{y}) clear. Max heat: {max_heat}°C. Coverage updated.")

    def rescue_victim(self, drone_id: str) -> str:
        """Extract confirmed victim at drone's current position."""
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
                drone.status_label = "RESUMING"
                msg = (f"[SUCCESS] Survivor {s['id']} extracted from ({drone.x},{drone.y}). "
                       f"Total rescued: {self.total_rescued}")
                self.log(msg, "SUCCESS", drone_id)
                return msg
        return f"No unrescued victim at ({drone.x},{drone.y})."

    def guide_victim(self, drone_id: str) -> str:
        """Instruction for drone to guide a mobile survivor back to base."""
        drone = self.drones.get(drone_id)
        if not drone: return "Drone not found"
        for s in self.zone.survivors:
            if s["x"] == drone.x and s["y"] == drone.y and s["found"] and not s["rescued"]:
                if s.get("can_move"):
                    drone.is_guiding = True
                    drone.guiding_victim_id = s["id"]
                    drone.target_x, drone.target_y = 0, 0
                    drone.status_label = "GUIDING TO BASE"
                    self.log(f"Drone {drone_id} guiding survivor {s['id']} to safety zone.", "INFO", drone_id)
                    return f"Guiding survivor {s['id']} to (0,0)."
                else:
                    return f"Survivor {s['id']} is unable to move. Stationary rescue required."
        return "No victim at current location."

    def get_estimated_finish_time(self) -> str:
        """Simple ETA based on remaining cells and active drones."""
        unscanned = len(self.get_unscanned_cells())
        active_cnt = len([d for d in self.drones.values() if d.status_label not in ["STANDBY", "OFFLINE (No Signal)"] and d.is_active])
        if active_cnt == 0: return "NA"
        # 0.7s per sim step, approx 1.5 steps per cell including scanning/turns
        seconds = (unscanned / active_cnt) * 1.5 * 0.7
        m, s = divmod(int(seconds), 60)
        return f"{m:02}m {s:02}s"

    def get_unscanned_cells(self) -> List[List[int]]:
        """Returns list of [x, y] not yet scanned."""
        return [
            [x, y]
            for y in range(GRID_H)
            for x in range(GRID_W)
            if not self.zone.scanned_cells[y][x]
        ]

    def get_status(self) -> Dict[str, Any]:
        scanned = sum(
            self.zone.scanned_cells[y][x]
            for y in range(GRID_H)
            for x in range(GRID_W)
        )
        coverage = float(round((scanned / (GRID_W * GRID_H)) * 100))
        return {
            "drones": [d.model_dump() for d in self.drones.values()],
            "zone": self.zone.model_dump(),
            "log": self.mission_log,
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

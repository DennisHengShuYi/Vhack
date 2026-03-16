import random
import sys
from enum import Enum
from typing import List, Dict, Any, Tuple
from drone import Drone, DroneStatus, CellState, Priority, chebyshev

class ZoneStatus(Enum):
    UNSCANNED = "UNSCANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"

class SimulationEngine:
    def __init__(self, width: int = 20, height: int = 15, num_survivors: int = 3):
        self.width = width
        self.height = height
        self.grid = self._initialize_grid()
        self.drones: Dict[str, Drone] = {}
        self.survivors: List[Dict[str, Any]] = []
        
        # Zone management
        self.zones: Dict[str, Dict[str, Any]] = {}
        self._partition_grid()
        
        # Randomize survivors based on user input
        self.simulated_survivor_locations = self._generate_survivors(num_survivors)
        
    def _initialize_grid(self) -> List[List[Dict[str, Any]]]:
        return [[{"state": CellState.UNSCANNED, "priority": Priority.MEDIUM} for _ in range(self.width)] for _ in range(self.height)]

    def _partition_grid(self, box_w: int = 5, box_h: int = 5):
        """Splits the grid into fixed bounding boxes and tracks their status."""
        zone_id = 0
        for sy in range(0, self.height, box_h):
            for sx in range(0, self.width, box_w):
                ex = min(sx + box_w - 1, self.width - 1)
                ey = min(sy + box_h - 1, self.height - 1)
                
                # Assign zone priority based on the first cell for now
                # In a real scenario, this might be the max priority of any cell in the zone
                p = self.grid[sy][sx]["priority"]
                
                self.zones[f"Z{zone_id}"] = {
                    "sx": sx, "sy": sy, "ex": ex, "ey": ey,
                    "status": ZoneStatus.UNSCANNED,
                    "assigned_to": None,
                    "priority": p
                }
                zone_id += 1
        print(f"[SIMULATION] Partitioned {self.width}x{self.height} grid into {len(self.zones)} zones.", file=sys.stderr, flush=True)

    def get_available_zones(self) -> List[Dict[str, Any]]:
        """Returns zones that are UNSCANNED (not assigned, not complete)."""
        available = []
        for zid, z in self.zones.items():
            if z["status"] == ZoneStatus.UNSCANNED:
                area = (z["ex"] - z["sx"] + 1) * (z["ey"] - z["sy"] + 1)
                available.append({
                    "zone_id": zid,
                    "sx": z["sx"], "sy": z["sy"],
                    "ex": z["ex"], "ey": z["ey"],
                    "scan_cost": area,
                    "priority": z["priority"]
                })
        return available

    def claim_zone(self, zone_id: str, drone_id: str) -> bool:
        """Mark a zone as IN_PROGRESS by a specific drone. Returns False if already claimed."""
        zone = self.zones.get(zone_id)
        if not zone:
            return False
        if zone["status"] != ZoneStatus.UNSCANNED:
            return False
        zone["status"] = ZoneStatus.IN_PROGRESS
        zone["assigned_to"] = drone_id
        return True

    def release_zone(self, zone_id: str):
        """Release a zone back to UNSCANNED (e.g. if drone had to abort)."""
        zone = self.zones.get(zone_id)
        if zone and zone["status"] == ZoneStatus.IN_PROGRESS:
            zone["status"] = ZoneStatus.UNSCANNED
            zone["assigned_to"] = None

    def _generate_survivors(self, count: int) -> List[Tuple[int, int]]:
        """Spawns exactly `count` survivors in random unique grid locations."""
        locations = set()
        while len(locations) < count:
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            locations.add((x, y))
        print(f"[SIMULATION] Generated {count} true survivor locations hidden on {self.width}x{self.height} map.", file=sys.stderr, flush=True)
        return list(locations)
        
    def spawn_drone(self, drone_id: str, x: int = 0, y: int = 0):
        self.drones[drone_id] = Drone(drone_id, x, y)
        
    def assign_scan_zone(self, drone_id: str, sx: int, sy: int, ex: int, ey: int) -> Dict[str, Any]:
        """Called by the MCP server when the LLM commands a drone."""
        drone = self.drones.get(drone_id)
        if not drone:
            return {"error": "Drone not found"}
            
        drone.assign_zone(sx, sy, ex, ey)
        return {
            "success": True, 
            "message": f"Assigned {drone_id} to bounding box {sx},{sy} -> {ex},{ey}"
        }
        
    def tick_simulation(self):
        """Advances the entire world by 1 grid movement for every drone."""
        for drone_id, drone in self.drones.items():
            scanned_coord = drone.tick()
            
            # Process the scan result
            if scanned_coord:
                cx, cy = scanned_coord
                # Prevent out of bounds
                if 0 <= cx < self.width and 0 <= cy < self.height:
                    if (cx, cy) in self.simulated_survivor_locations:
                        self.grid[cy][cx]["state"] = CellState.SURVIVOR_DETECTED
                        print(f"!!! {drone_id} DETECTED SURVIVOR AT ({cx}, {cy})", file=sys.stderr, flush=True)
                        if not any(s["location"] == (cx, cy) for s in self.survivors):
                           self.survivors.append({"id": f"S_{cx}_{cy}", "location": (cx, cy), "confirmed_by": drone_id})
                    else:
                        self.grid[cy][cx]["state"] = CellState.CLEAR

            # Check if drone just became IDLE and had a zone — auto-complete it
            if drone.status == DroneStatus.IDLE:
                for zid, z in self.zones.items():
                    if z["assigned_to"] == drone_id and z["status"] == ZoneStatus.IN_PROGRESS:
                        z["status"] = ZoneStatus.COMPLETE
                        print(f"[SIMULATION] Zone {zid} completed by {drone_id}.", file=sys.stderr, flush=True)
            
            # Check if drone is RETURNING (aborted) — release its zone
            if drone.status == DroneStatus.RETURNING:
                for zid, z in self.zones.items():
                    if z["assigned_to"] == drone_id and z["status"] == ZoneStatus.IN_PROGRESS:
                        self.release_zone(zid)
                        print(f"[SIMULATION] Zone {zid} released by {drone_id} (aborted).", file=sys.stderr, flush=True)

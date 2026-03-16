import math
import sys
from enum import Enum
from typing import List, Tuple, Dict, Any, Optional

class CellState(Enum):
    UNSCANNED = "UNSCANNED"
    CLEAR = "CLEAR"
    SURVIVOR_DETECTED = "SURVIVOR_DETECTED"
    INACCESSIBLE = "INACCESSIBLE"

class DroneStatus(Enum):
    IDLE = "IDLE"
    ON_MISSION = "ON_MISSION"
    RETURNING = "RETURNING"
    CHARGING = "CHARGING"

class Priority(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

def chebyshev(x1: int, y1: int, x2: int, y2: int) -> int:
    return max(abs(x2 - x1), abs(y2 - y1))

class Drone:
    def __init__(self, drone_id: str, start_x: int, start_y: int):
        self.drone_id = drone_id
        self.x = start_x
        self.y = start_y
        self.battery = 100
        self.status = DroneStatus.IDLE
        self.assigned_zone: Optional[Tuple[int, int, int, int]] = None
        self.path_queue: List[Tuple[int, int]] = []
        self.scanned_grids = 0
        self.base_pos = (0, 0)
        
    def assign_zone(self, start_x: int, start_y: int, end_x: int, end_y: int):
        """Generates a path sequence including transit to the closest corner and a zig-zag scan."""
        self.assigned_zone = (start_x, start_y, end_x, end_y)
        self.path_queue = []
        self.status = DroneStatus.ON_MISSION
        self.scanned_grids = 0
        
        # 1. Determine which of the 4 corners is closest to minimize transit
        corners = [
            (start_x, start_y), # Top-Left
            (end_x, start_y),   # Top-Right
            (start_x, end_y),   # Bottom-Left
            (end_x, end_y)      # Bottom-Right
        ]
        
        best_corner = corners[0]
        min_dist = chebyshev(self.x, self.y, corners[0][0], corners[0][1])
        
        for i in range(1, 4):
            d = chebyshev(self.x, self.y, corners[i][0], corners[i][1])
            if d < min_dist:
                min_dist = d
                best_corner = corners[i]
        
        target_sx, target_sy = best_corner
        
        # 2. Transit Path to the chosen corner
        curr_x, curr_y = self.x, self.y
        
        # If already at target corner, add it to queue so we scan it in the first tick
        if (curr_x, curr_y) == (target_sx, target_sy):
             self.path_queue.append((curr_x, curr_y))
             
        while (curr_x, curr_y) != (target_sx, target_sy):
            if curr_x < target_sx: curr_x += 1
            elif curr_x > target_sx: curr_x -= 1
            if curr_y < target_sy: curr_y += 1
            elif curr_y > target_sy: curr_y -= 1
            self.path_queue.append((curr_x, curr_y))

        # 3. Zig-Zag Scan starting from the chosen corner
        # We need to adapt the zig-zag based on which corner we started at
        rev_x = (target_sx == end_x)
        rev_y = (target_sy == end_y)
        
        y_range = range(start_y, end_y + 1)
        if rev_y:
            y_range = range(end_y, start_y - 1, -1)
            
        for i, y in enumerate(y_range):
            # Normal row scan or reversed row scan
            # i % 2 == 0 is the first row of scan, should match the rev_x orientation
            if i % 2 == 0:
                if not rev_x:
                    xs = range(start_x, end_x + 1)
                else:
                    xs = range(end_x, start_x - 1, -1)
            else:
                if not rev_x:
                    xs = range(end_x, start_x - 1, -1)
                else:
                    xs = range(start_x, end_x + 1)
                
            for x in xs:
                # Avoid adding the same point twice (e.g. if it was the end of transit)
                if not self.path_queue or self.path_queue[-1] != (x, y):
                    # Always add to queue. If it matches current pos, 
                    # the first tick will 'move' to current pos and scan it.
                    self.path_queue.append((x, y))

    def return_to_base(self):
        """Forces the drone to abort its mission and head home."""
        self.status = DroneStatus.RETURNING
        self.path_queue = []
        
    def tick(self) -> Optional[Tuple[int, int]]:
        """Moves the drone 1 grid along its path or home. Returns coordinates scanned."""
        if self.status == DroneStatus.CHARGING:
            self.battery = min(100, self.battery + 20)
            if self.battery == 100:
                self.status = DroneStatus.IDLE
            return None
            
        if self.status == DroneStatus.RETURNING:
            # Move towards base
            if (self.x, self.y) == self.base_pos:
                self.status = DroneStatus.CHARGING
                return None
            return self._move_one_step_towards(self.base_pos[0], self.base_pos[1])

        if self.status == DroneStatus.ON_MISSION:
            if not self.path_queue:
                # Finished zone - Stay where we are and wait for next command
                self.status = DroneStatus.IDLE
                print(f"[SIMULATION] {self.drone_id} finished zone and is now IDLE at ({self.x}, {self.y})", file=sys.stderr, flush=True)
                return None
                
            next_x, next_y = self.path_queue[0]
            
            # Check battery bounds BEFORE moving
            # Use Chebyshev distance as it matches diagonal movement (8-connectivity)
            dist_home = chebyshev(next_x, next_y, self.base_pos[0], self.base_pos[1])
            if (self.battery - 1) <= dist_home:
                # Critically low battery, abort
                print(f"[SIMULATION] {self.drone_id} Low Battery! Aborting mission and returning home.", file=sys.stderr)
                self.status = DroneStatus.RETURNING
                self.path_queue = []
                return None
                
            # Perform move
            self.path_queue.pop(0)
            
            # Since Euclidean distance is continuous, but grid movement is atomic,
            # we subtract 1% per grid move block (as per requirements)
            self.battery -= 1
            self.x, self.y = next_x, next_y
            self.scanned_grids += 1
            print(f"[SIMULATION] {self.drone_id} flew to ({self.x}, {self.y}). Battery: {self.battery}%.", file=sys.stderr)
            return (self.x, self.y)
            
        return None

    def _move_one_step_towards(self, target_x: int, target_y: int) -> None:
        """Helper to move 1 step towards target (mostly for returning to base)"""
        # Calculate direction vector
        dx = target_x - self.x
        dy = target_y - self.y
        
        # Move 1 grid step in the dominant axis
        if self.x < target_x: self.x += 1
        elif self.x > target_x: self.x -= 1
        
        if self.y < target_y: self.y += 1
        elif self.y > target_y: self.y -= 1
            
        self.battery -= 1

"""
Drone Swarm MCP Server — Exposes drone control tools via Model Context Protocol.

All Agent↔Drone communication flows through these standardized MCP tools.
Hard-coding drone movements is prohibited — the LLM must call these tools.
"""
from fastmcp import FastMCP
import shared
from typing import List, Dict, Any
import random

mcp = FastMCP(
    name="RescueSwarmMCP",
    instructions=(
        "You are the MCP interface to a rescue drone swarm. "
        "All drone control MUST go through these tools. "
        "Always call list_drones() first to discover active drones."
    ),
)


# ─── Tool 1: Real-time Fleet Discovery ─────────────────────────────────────────
@mcp.tool()
def list_drones() -> List[str]:
    """
    🔍 Real-time swarm discovery — returns active drone IDs from the mesh network.

    Simulates a heartbeat system: some drones may randomly fail to respond (only 3-5 active).
    The Command Agent MUST call this first. Drone IDs are never hard-coded.
    Returns a list of all online drone IDs (e.g. ['ALPHA-1', 'ALPHA-2', ...]).
    """
    return shared.sim.simulate_heartbeats()


# ─── Tool 2: Full Telemetry ─────────────────────────────────────────────────────
@mcp.tool()
def get_drone_status(drone_id: str) -> Dict[str, Any]:
    """
    📡 Get complete telemetry for a single drone.

    Returns: id, x, y position, battery%, is_charging, returning_to_base,
             is_waiting_response (victim found), target_x/y, status_label.

    Call this for every drone before making planning decisions.
    """
    if drone_id not in shared.sim.drones:
        return {"error": f"Drone '{drone_id}' not found. Call list_drones() first."}
    d = shared.sim.drones[drone_id]
    return {
        "id": d.id,
        "x": d.x,
        "y": d.y,
        "battery": round(d.battery, 1) if d.battery is not None else None,
        "is_charging": d.is_charging,
        "returning_to_base": d.returning_to_base,
        "is_waiting_response": d.is_waiting_response,
        "target_x": d.target_x,
        "target_y": d.target_y,
        "status_label": d.status_label,
        "charge_cycles": d.charge_cycles,
        "victim_report": d.victim_report,
        "is_guiding": d.is_guiding,
        "terrain": shared.sim.zone.terrain_types[d.y][d.x]
    }


# ─── Tool 3: Navigate ──────────────────────────────────────────────────────────
@mcp.tool()
def move_to(drone_id: str, x: int, y: int) -> str:
    """
    🚁 Command drone to navigate to grid coordinate (x, y).

    Grid: 10×10 (coordinates 0–9 for both x and y). Base station at (0,0).
    Battery cost: 2% per cell (Manhattan distance).
    Returns warning if battery insufficient — recall to charge first.

    CRITICAL: Always check battery before moving distant drones.
    """
    return shared.sim.move_drone(drone_id, x, y)


# ─── Tool 4: Thermal Scan ──────────────────────────────────────────────────────
@mcp.tool()
def thermal_scan(drone_id: str) -> str:
    """
    🌡️ Execute 5×5 thermal sensor scan at drone's current position.

    Uses simulated CNN model: detects human heat signatures (>78° with 28+ contrast).
    Returns confidence %, thermal report, and triage priority if survivor found.
    Battery cost: 1% per scan. Must call at each sector for coverage.

    If THERMAL MATCH found: drone enters VICTIM STANDBY — do NOT move it.
    """
    return shared.sim.scan(drone_id)


# ─── Tool 5: Charging ──────────────────────────────────────────────────────────
@mcp.tool()
def initiate_charging(drone_id: str) -> str:
    """
    🔋 Begin emergency charging sequence at base station (0,0).

    Charges 25% per call. Drone MUST be at (0,0).
    Call move_to(drone_id, 0, 0) first if not already at base.

    RECALL POLICY: ANY drone below 25% battery MUST be recalled immediately.
    """
    return shared.sim.charge_step(drone_id)


# ─── Tool 6: Rescue ────────────────────────────────────────────────────────────
@mcp.tool()
def rescue_victim(drone_id: str) -> str:
    """
    🚑 Attempt victim extraction at drone's current location.

    Only succeeds if thermal_scan() already confirmed a survivor here.
    After rescue, drone status changes to RESUMING — AI should assign next target.
    Returns success/failure with survivor ID.
    """
    return shared.sim.rescue_victim(drone_id)


# ─── Tool 7: Guide to Safety ───────────────────────────────────────────────────
@mcp.tool()
def guide_to_safety(drone_id: str) -> str:
    """
    🚶 Instruction for drone to guide a mobile survivor back to base station.
    
    Only works if the survivor at the current position is labeled 
    '[SURVIVOR ABLE TO MOVE]'.
    The drone will lock onto the survivor and return to (0,0) together.
    """
    return shared.sim.guide_victim(drone_id)


# ─── Tool 7: Coverage Map ──────────────────────────────────────────────────────
@mcp.tool()
def get_unscanned_sectors() -> List[List[int]]:
    """
    🗺️ Returns list of [x, y] coordinates NOT yet scanned.

    Use this to find optimal scan targets and distribute drones across the zone.
    Returns empty list when all 100 sectors are covered.
    """
    return shared.sim.get_unscanned_cells()


# ─── Tool 8: Mission Overview ──────────────────────────────────────────────────
@mcp.tool()
def get_mission_status() -> Dict[str, Any]:
    """
    📊 High-level mission statistics.

    Returns: coverage_pct, total_victims, victims_found, victims_rescued,
             mission_active, elapsed_ts.

    Use to decide if mission is complete (all victims rescued).
    """
    return shared.sim.get_status()["stats"]


if __name__ == "__main__":
    mcp.run()

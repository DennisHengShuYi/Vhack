import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from fastmcp import FastMCP
from typing import Dict, Any, List
from simulation import SimulationEngine, DroneStatus, CellState

# Initialize the MCP Server
mcp = FastMCP("DroneCommandServer")

# Initialize the global simulation state
sim_engine = SimulationEngine()
simulation_active = False

# -------------------------------------------------------------------
# WebSocket Connection Manager
# -------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send initial state
        await self.broadcast_state()

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_state(self):
        # Package the grid and drones for the frontend
        state = {
            "type": "state_update",
            "grid": [[{"state": cell["state"].name, "priority": cell["priority"].name} for cell in row] for row in sim_engine.grid],
            "drones": {d_id: {"x": d.x, "y": d.y, "battery": d.battery, "status": d.status.name} for d_id, d in sim_engine.drones.items()},
            "survivors_found": len(sim_engine.survivors),
            "total_survivors": len(sim_engine.simulated_survivor_locations),
            "hidden_survivors": sim_engine.simulated_survivor_locations # True locations for initial visibility
        }
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(state)
            except Exception:
                dead_connections.append(connection)
        
        for dead in dead_connections:
            self.active_connections.remove(dead)
            
    async def broadcast_log(self, log_msg: str, is_stream: bool = False):
        payload = {"type": "log", "message": log_msg}
        if is_stream:
            payload["is_stream"] = True
        for connection in self.active_connections:
            try:
                await connection.send_json(payload)
            except Exception:
                pass

manager = ConnectionManager()

# -------------------------------------------------------------------
# Background Simulation Tick
# -------------------------------------------------------------------
async def run_simulation_loop():
    global simulation_active
    while True:
        if simulation_active:
            sim_engine.tick_simulation()
            await manager.broadcast_state()
        await asyncio.sleep(1.0) # Tick every 1 second

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the simulation loop when the FastAPI server starts
    loop_task = asyncio.create_task(run_simulation_loop())
    yield
    loop_task.cancel()

# Initialize FastAPI
app = FastAPI(lifespan=lifespan)

# Allow CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False, # Must be False if allow_origins is ["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# FastAPI Endpoints for UI Controls
# -------------------------------------------------------------------

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Drone Swarm Backend is running."}

class StartParams(BaseModel):
    survivor_count: int

class LogMessage(BaseModel):
    text: str
    is_stream: bool = False

@app.post("/start")
async def start_simulation(params: StartParams):
    global sim_engine, simulation_active
    # Reinitialize a fresh simulation environment with optimized rectangular grid
    sim_engine = SimulationEngine(width=20, height=15, num_survivors=params.survivor_count)
    sim_engine.spawn_drone("drone_1", 0, 0)
    sim_engine.spawn_drone("drone_2", 19, 0)
    sim_engine.spawn_drone("drone_3", 0, 14)
    simulation_active = True
    await manager.broadcast_log(f"Simulation started. {params.survivor_count} survivors hidden.")
    return {"status": "started"}

@app.post("/stop")
async def stop_simulation():
    global simulation_active
    simulation_active = False
    await manager.broadcast_log("Simulation manually stopped.")
    return {"status": "stopped"}

@app.post("/log")
async def receive_agent_log(msg: LogMessage):
    # The agent posts its thoughts here so we can broadcast them to WebSockets
    await manager.broadcast_log(msg.text, is_stream=msg.is_stream)
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# -------------------------------------------------------------------
# MCP Tools Exposed to the Agent
# -------------------------------------------------------------------

@mcp.tool()
def list_drones() -> str:
    """Returns a list of all active drone IDs on the network."""
    drones = sim_engine.drones.keys()
    return f"Active Drones: {', '.join(drones)}"

@mcp.tool()
def get_status(drone_id: str) -> str:
    """Gets the current status (battery, location) of a specific drone."""
    drone = sim_engine.drones.get(drone_id)
    if not drone:
        return f"Error: Drone {drone_id} not found."
    
    return f"Status of {drone_id}: Battery={round(drone.battery, 2)}%, Location=({drone.x}, {drone.y}), State={drone.status.name}"

@mcp.tool()
def assign_scan_zone(drone_id: str, zone_id: str) -> str:
    """
    Commands a drone to sweep a pre-defined zone by its zone_id.
    Use get_grid_state to see available zones first.
    Args:
        drone_id: The ID of the drone.
        zone_id: The zone ID from the available zones list (e.g. 'Z0', 'Z5').
    """
    drone = sim_engine.drones.get(drone_id)
    if not drone:
        return f"Error: Drone {drone_id} not found."
    if drone.status != DroneStatus.IDLE:
        return f"Error: Drone {drone_id} is currently {drone.status.name}. Wait until IDLE."
    
    # Look up zone
    zone = sim_engine.zones.get(zone_id)
    if not zone:
        return f"Error: Zone {zone_id} does not exist. Use get_grid_state to see valid zone IDs."
    
    # Try to claim the zone
    from simulation import ZoneStatus
    if zone["status"] != ZoneStatus.UNSCANNED:
        return f"Error: Zone {zone_id} is already {zone['status'].name}. Pick a different zone."
    
    sx, sy, ex, ey = zone["sx"], zone["sy"], zone["ex"], zone["ey"]
    
    # --- Pre-Flight Battery Validation ---
    from drone import chebyshev
    transit_cost = chebyshev(drone.x, drone.y, sx, sy)
    scan_cost = (abs(ex - sx) + 1) * (abs(ey - sy) + 1)
    return_cost = chebyshev(ex, ey, 0, 0)
    total_estimated_cost = transit_cost + scan_cost + return_cost
    
    if drone.battery < total_estimated_cost:
        return f"Error: Drone {drone_id} has {round(drone.battery, 1)}% battery, but zone {zone_id} requires ~{round(total_estimated_cost, 1)}%. REJECTED. Pick a closer zone or return_to_base."
    # --------------------------------------
    
    # Claim zone and dispatch drone
    sim_engine.claim_zone(zone_id, drone_id)
    result = sim_engine.assign_scan_zone(drone_id, sx, sy, ex, ey)
    return f"SUCCESS: {result['message']} (Zone {zone_id} claimed)"

@mcp.tool()
def return_to_base(drone_id: str) -> str:
    """Forces a drone to immediately abort its mission and return to base (0,0)."""
    drone = sim_engine.drones.get(drone_id)
    if not drone:
        return f"Error: Drone {drone_id} not found."
        
    drone.return_to_base()
    return f"Drone {drone_id} is aborting mission and returning to base."

@mcp.tool()
def get_grid_state() -> str:
    """Returns a list of available (unscanned, unclaimed) zones that drones can be assigned to. Each zone has a zone_id, coordinates, and scan_cost."""
    available = sim_engine.get_available_zones()
    unscanned_count = sum(1 for row in sim_engine.grid for cell in row if cell["state"].name == "UNSCANNED")
    survivors = len(sim_engine.survivors)
    
    if not available:
        return f"ALL ZONES COMPLETE. Grid {sim_engine.width}x{sim_engine.height}. Unscanned cells: {unscanned_count}. Survivors Found: {survivors}."
    
    zone_list = []
    for z in available:
        zone_list.append(f"  {z['zone_id']}: ({z['sx']},{z['sy']})->({z['ex']},{z['ey']}) scan_cost={z['scan_cost']}")
    
    header = f"Grid {sim_engine.width}x{sim_engine.height}. Unscanned cells: {unscanned_count}. Survivors Found: {survivors}.\nAvailable Zones ({len(available)}):\n"
    return header + "\n".join(zone_list)

@mcp.tool()
def get_idle_drones() -> str:
    """
    Returns a 'Mission Options Menu' for all idle drones. 
    The agent must evaluate these options based on battery, priority, and risk, 
    then execute the chosen assignments.
    """
    from drone import chebyshev
    
    idle_drones = []
    for d_id, d in sim_engine.drones.items():
        if d.status == DroneStatus.IDLE:
            idle_drones.append((d_id, d))
    
    if not idle_drones:
        return "NO_IDLE_DRONES: No drones currently need orders."
    
    available = sim_engine.get_available_zones()
    survivors = len(sim_engine.survivors)
    total_survivors = len(sim_engine.simulated_survivor_locations)
    
    if not available:
        drone_names = ", ".join(d_id for d_id, _ in idle_drones)
        return f"MISSION COMPLETE: Grid fully searched. Found {survivors}/{total_survivors} survivors. Drones available for recall: {drone_names}"
    
    report = [f"--- MISSION OPTIONS MENU (Found: {survivors}/{total_survivors}) ---"]
    
    for d_id, drone in idle_drones:
        report.append(f"\n[DRONE: {d_id}] Battery: {round(drone.battery, 1)}% @ ({drone.x}, {drone.y})")
        
        # Calculate options for this specific drone
        options = []
        for z in available:
            transit = chebyshev(drone.x, drone.y, z["sx"], z["sy"])
            return_cost = chebyshev(z["ex"], z["ey"], 0, 0)
            total_needed = transit + z["scan_cost"] + return_cost
            
            # Use a slightly more sophisticated priority-dist weighting
            score = (100 if z["priority"].name == "HIGH" else 50) - (transit * 1.5)
            options.append({
                "zone_id": z["zone_id"],
                "transit": transit,
                "scan": z["scan_cost"],
                "return": return_cost,
                "total": total_needed,
                "priority": z["priority"].name,
                "score": score
            })
            
        # Sort by score (priority + distance)
        options.sort(key=lambda x: x["score"], reverse=True)
        
        # Take top 3 valid options
        valid_options = [o for o in options if o["total"] <= drone.battery][:3]
        
        if not valid_options:
            report.append("  * REC: return_to_base() | Battery too low for any zone.")
        else:
            for i, opt in enumerate(valid_options):
                risk = "LOW" if drone.battery - opt["total"] > 20 else ("MEDIUM" if drone.battery - opt["total"] > 10 else "HIGH")
                report.append(
                    f"  Opt {i+1}: assign_scan_zone(\"{d_id}\", \"{opt['zone_id']}\") - Priority={opt['priority']}, Cost={opt['total']}, Risk={risk}"
                )
    
    return "\n".join(report)

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
if __name__ == "__main__":
    import threading
    import sys
    import time
    
    # CRITICAL: MCP uses stdout for its protocol. 
    # Any print() in the main thread or sub-threads NOT directed to stderr 
    # will break the Agent connection.

    def run_api_server():
        # Set Windows-specific event loop policy for the background thread
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Give a moment for any previous sockets to clear
        time.sleep(1.0)
            
        print("Starting FastAPI / WebSocket server on http://127.0.0.1:8000", file=sys.stderr, flush=True)
        try:
            import copy
            # host="127.0.0.1" is often safer than "0.0.0.0" on local Windows machines
            # Use log_config to redirect all logging to stderr
            log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
            log_config["handlers"]["default"]["stream"] = "ext://sys.stderr"
            log_config["handlers"]["access"]["stream"] = "ext://sys.stderr"
            
            uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info", log_config=log_config)
        except OSError as e:
            if e.errno == 10048:
                print("\n[ERROR] Port 8000 is already in use by another process. Please close other instances of the server.", file=sys.stderr, flush=True)
            else:
                print(f"[ERROR] Failed to start FastAPI server: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[ERROR] Unexpected error in API thread: {e}", file=sys.stderr, flush=True)
        
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    print("Starting FastMCP stdio server...", file=sys.stderr, flush=True)
    mcp.run()

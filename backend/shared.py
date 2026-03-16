"""
Shared simulation state — imported by both server.py (FastAPI + MCP tools)
so they always reference the same SimulationState instance.
"""
from simulation import SimulationState

sim = SimulationState()

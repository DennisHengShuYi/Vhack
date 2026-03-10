"""
Shared simulation state — imported by both drone_mcp.py and main.py
so they always reference the same SimulationState instance.
"""
from simulation import SimulationState

sim = SimulationState()

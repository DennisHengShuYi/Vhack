"""
Verify (19,14) is accessible and a drone will be dispatched there via victim-response.
"""
import requests, time, sys

BASE = "http://127.0.0.1:8000"

print("Resetting...", flush=True)
requests.post(f"{BASE}/reset?num_victims=5")
requests.post(f"{BASE}/run-mission")
time.sleep(2)

state = requests.get(f"{BASE}/state").json()
zone = state["zone"]

# Check accessibility of (19,14)
h19_14 = zone["hazard_cells"][14][19]
print(f"(19,14) is hazard: {h19_14}")

# Force ALPHA-1 into victim standby by manipulating via API
# Simulate: just call the endpoint directly — the endpoint rescues the victim too
# so we need a drone that's actually in victim_standby or just call it cold
drone_id = state["drones"][0]["id"]
print(f"Forcing victim-response on {drone_id} with '19 and 14'...")
resp = requests.post(f"{BASE}/victim-response?drone_id={drone_id}&operator_message=19+and+14")
print(f"Response: {resp.json()}")

time.sleep(3)
state2 = requests.get(f"{BASE}/state").json()

# Show AI logs
print("\n--- Last 10 AI/VERBAL logs ---")
for l in [x for x in state2["log"] if x["level"].lower() in ("ai","verbal","warn")][-10:]:
    print(f"  [{l['level']}][{l.get('drone','')}] {l['text'][:300]}")

# Check drone targets
print("\n--- Drone targets ---")
for d in state2["drones"]:
    print(f"  {d['id']}: voice={d.get('voice_override')} target=({d.get('target_x')},{d.get('target_y')}) path={len(d.get('path_queue',[]))}")

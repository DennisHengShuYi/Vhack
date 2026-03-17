import requests, json, sys

BASE = "http://127.0.0.1:8000"

# 1. Get state
state = requests.get(f"{BASE}/state").json()
stats = state.get("stats", {})
drones = state.get("drones", [])

print("Mission active:", stats.get("mission_active"))
print("Drones:")
for d in drones:
    print(f"  {d['id']}: pos=({d['x']},{d['y']}) status={d['status_label']!r} voice={d.get('voice_override')} target=({d.get('target_x')},{d.get('target_y')}) path_len={len(d.get('path_queue',[]))} battery={d['battery']:.0f}%")

print("\nRecent logs:")
for l in state.get("log", [])[-10:]:
    if l["level"].lower() in ("ai", "error", "warn", "verbal"):
        print(f"  [{l['level']}] {l['text'][:150]}")

# 2. Send a test voice command
print("\n--- Sending voice command: 'move to 7 and 3' ---")
resp = requests.post(f"{BASE}/voice-command?message=move+to+7+and+3")
print("API response:", resp.json())

import time
time.sleep(3)

# 3. Check state after
state2 = requests.get(f"{BASE}/state").json()
print("\nPost-command drones:")
for d in state2.get("drones", []):
    print(f"  {d['id']}: pos=({d['x']},{d['y']}) status={d['status_label']!r} voice={d.get('voice_override')} target=({d.get('target_x')},{d.get('target_y')}) path_len={len(d.get('path_queue', []))}")

print("\nPost-command AI logs:")
for l in state2.get("log", [])[-12:]:
    if l["level"].lower() in ("ai", "error", "warn", "verbal"):
        print(f"  [{l['level']}] {l['text'][:200]}")

import requests
import time

API_BASE = "http://127.0.0.1:8000"

print("Resetting mission...")
requests.post(f"{API_BASE}/reset?num_victims=10")
time.sleep(1)

print("Starting mission...")
requests.post(f"{API_BASE}/run-mission")
time.sleep(5) # Wait for agent to process

print("Checking state...")
resp = requests.get(f"{API_BASE}/state")
data = resp.json()

logs = data.get("log", [])
print("\n--- RECENT LOGS ---")
for log in logs[-10:]:
    print(f"[{log['ts']}][{log['level']}] {log['text']}")

drones = data.get("drones", [])
print("\n--- DRONE STATUS ---")
for d in drones:
    print(f"{d['id']}: Status={d['status_label']} Pos=({d['x']},{d['y']}) Target=({d['target_x']},{d['target_y']})")

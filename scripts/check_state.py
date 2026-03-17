import requests
import json

try:
    resp = requests.get("http://127.0.0.1:8000/state")
    data = resp.json()
    logs = data.get("log", [])
    print("--- LAST 5 LOG ENTRIES ---")
    for log in logs[-5:]:
        print(f"[{log['ts']}][{log['level']}] {log['text']}")
    
    drones = data.get("drones", [])
    print("\n--- DRONE STATUS ---")
    for d in drones:
        print(f"{d['id']}: Status={d['status_label']} Pos=({d['x']},{d['y']}) Target=({d['target_x']},{d['target_y']})")
except Exception as e:
    print(f"Error: {e}")

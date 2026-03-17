import requests
import time
import json

BASE_URL = "http://127.0.0.1:8000"

def test_voice():
    # 1. Reset and start mission
    print("Resetting simulation...")
    requests.post(f"{BASE_URL}/reset?num_victims=5")
    requests.post(f"{BASE_URL}/run-mission")
    time.sleep(2)

    # 2. Send voice command
    # The prompt says 'X and Y' is primary.
    command = "move to 10 and 5"
    print(f"Sending voice command: '{command}'")
    resp = requests.post(f"{BASE_URL}/voice-command?message={command}")
    print(f"Response: {resp.json()}")

    # 3. Poll state for 10 seconds and check if any drone is moving to (10,5)
    print("Polling state to verify movement...")
    for _ in range(20):
        state = requests.get(f"{BASE_URL}/state").json()
        ai_logs = [l for l in state['log'] if l.get('level') == 'AI']
        for l in ai_logs[-2:]: # show last couple of AI decisions
            print(f"[{l['ts']}] AI VOICE REASONING: \n{l['text']}")
        
        voice_drones = [d for d in state['drones'] if d.get('voice_override')]
        if voice_drones:
            d = voice_drones[0]
            print(f"Drone {d['id']} is on VOICE mission to ({d['target_x']},{d['target_y']}). Current pos: ({d['x']},{d['y']}). Status: {d['status_label']}")
            if d['x'] == 10 and d['y'] == 5:
                print("SUCCESS: Drone reached the target!")
                # Check return path
                time.sleep(2)
                state = requests.get(f"{BASE_URL}/state").json()
                d_after = next(drone for drone in state['drones'] if drone['id'] == d['id'])
                print(f"Status after reaching target: {d_after['status_label']}. Resume Point: {d_after.get('original_pos')}")
                return
        else:
            print("No voice override drones active yet...")
        time.sleep(1)

if __name__ == "__main__":
    test_voice()

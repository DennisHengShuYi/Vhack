"""
Quick diagnostic: what does the AI actually return for '19 and 14' in victim-response context?
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
import llm_gateway

parse_prompt = (
    "You are a rescue grid dispatcher AI.\n"
    "An operator entered this message: '19 and 14'\n"
    "\n"
    "TASK: Extract any grid coordinate reference from the message.\n"
    "The operator may be directing a drone to a location, OR reporting where\n"
    "another survivor is. Treat ALL coordinate patterns the same way.\n"
    "\n"
    "Grid is 20 wide (x: 0-19), 15 tall (y: 0-14).\n"
    "\n"
    "COORDINATE FORMAT RULES - apply strictly in order:\n"
    "1. PRIMARY: 'X and Y' -> ALWAYS treat as coordinate [X, Y]\n"
    "   '19 and 14' -> [19, 14]  |  '0 and 10' -> [0, 10]  |  '5 and 3' -> [5, 3]\n"
    "2. Two bare integers separated by space or comma: treat as [X, Y]\n"
    "   '19 14' -> [19, 14]  |  '19,14' -> [19, 14]\n"
    "3. 'grid N' (N is 0-299): x = N % 20, y = N // 20\n"
    "4. '(X,Y)' bracket notation: map directly\n"
    "5. Vague ('middle', 'sector N', 'north'): infer closest grid cell\n"
    "\n"
    "IMPORTANT: If the message contains ANY two numbers, extract them as coordinates.\n"
    "\n"
    "Return ONLY valid JSON:\n"
    "  {\"target\": [x, y], \"reason\": \"brief explanation\"}\n"
    "  {} (only if message contains NO number references at all)"
)

print("Calling LLM with prompt for '19 and 14'...", flush=True)
resp = llm_gateway.completion(messages=[{"role": "user", "content": parse_prompt}])
raw = resp.choices[0].message.content.strip()
print(f"RAW RESPONSE: {raw}")

import json
try:
    data = json.loads(raw.replace("```json", "").replace("```", "").strip())
    print(f"PARSED: {data}")
    if data.get("target"):
        print(f"SUCCESS: target={data['target']}")
    else:
        print("FAILED: No target in response")
except Exception as e:
    print(f"JSON PARSE ERROR: {e}")

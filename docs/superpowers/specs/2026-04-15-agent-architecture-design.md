# Agent Architecture Improvements — Design Spec
**Date:** 2026-04-15
**Scope:** `agent/` directory — refactor into helper modules (Group A: implement; Group B: stub)

---

## 1. Context & Motivation

The SENTINEL agent currently lives entirely in `agent/agent.py` (~470 lines). All concerns — mission memory, rule-based fallback, token streaming, MCP connection, tick loop — are mixed in a single class. Judge feedback specifically called out:

- No cross-mission learning / flat memory loses critical survivor intel
- Rule-based fallback is greedy with no priority scoring
- No self-monitoring or performance contracts
- No LLM-vs-fallback benchmarking capability

These improvements address all four points while keeping the single-process MCP stdio architecture intact.

**Hard constraint:** The agent and drones never know the total number of victims or the location of unfound victims. All contracts, memory events, and alerts must respect this — only observable data (coverage %, zone scores, battery, drone status, found survivors) is used.

---

## 2. Current Architecture

```
agent/
  agent.py    # 470 lines — owns everything
```

### Key methods in AgentOrchestrator
| Method | Role |
|--------|------|
| `run_mission_loop()` | MCP connect, tick loop, LLM invoke |
| `_extract_memory_events()` | Parses tool results → flat `list[str]`, capped at 8 |
| `_rule_based_assignments()` | Greedy parser — first valid Opt per drone |
| `_execute_rule_based()` | Sequential `await session.call_tool()` per action |
| `_is_trivial()` | True if every drone has exactly 1 option |
| `TokenStreamHandler` | Streams LLM tokens to frontend |

### Existing MCP tools (all in `backend/mcp_tools.py`)
All tools needed by improvements already exist:
`get_idle_drones`, `assign_scan_zone`, `return_to_base`, `split_scan_zone`,
`reassign_drone`, `get_probability_map`, `get_survivor_intel`, `get_mission_intel`,
`get_thermal_scan`, `get_swarm_status`

---

## 3. Target Module Structure

```
agent/
  agent.py          # slim orchestrator (~280 lines)
  memory.py         # MissionMemory — tiered event storage + prompt injection
  contracts.py      # ContractChecker — 4 rules evaluated each tick
  fallback.py       # WeightedPlanner — scored assignments, replaces greedy parser
  session_log.py    # [Group B stub] JSONL tick logger
  hooks.py          # [Group B stub] Pre/PostToolUse validation layer
```

`agent.py` retains ownership of:
- MCP connection and LangGraph agent creation
- `TokenStreamHandler` (token streaming to frontend)
- HTTP log broadcasting (`_broadcast_log`, `_stream_log`)
- Tick loop (POLL → CONTRACT CHECK → EXECUTE)

Everything else is delegated to helper modules.

---

## 4. Group A — Implementation

### 4.1 `memory.py` — MissionMemory

Replaces the flat `list[str]` with three priority tiers. The `_extract_memory_events()` method moves here.

```python
class MissionMemory:
    tier0: list[str]  # cap 6  — never dropped
    tier1: list[str]  # cap 5  — compressed last
    tier2: list[str]  # cap 3  — compressed first

    def extract(self, messages: list, tick: int) -> None
    def to_prompt_block(self) -> str   # injects into LLM prompt
    def reset(self) -> None            # called on mission start
```

**Event classification:**

| Pattern in tool result | Tier | Example entry |
|---|---|---|
| "survivor" + "found/detected" | 0 | `Tick 12: Survivor at (4,7) — P1-CRITICAL` |
| "CRITICAL" triage | 0 | `Tick 15: P1-CRITICAL awaiting rescue at (4,7)` |
| Drone offline / failure | 0 | `Tick 20: ALPHA-3 offline` |
| `split_scan_zone` success | 1 | `Tick 8: Z2 split — ALPHA-1 + ALPHA-4` |
| `reassign_drone` called | 1 | `Tick 31: ALPHA-2 redirected Z5→Z1` |
| Zone completed | 1 | `Tick 18: Z0 complete` |
| Battery RTB | 1 | `Tick 22: ALPHA-1 RTB 24%` |
| Routine `assign_scan_zone` | 2 | `Tick 5: ALPHA-3→Z6` |
| Thermal anomaly | 2 | `Tick 9: Anomaly near Z3 boundary` |

**`to_prompt_block()`:** Tier 0 is always included. Tier 1 and 2 are appended only while the total block stays under 400 tokens. Survivor locations (tier 0) are never evicted regardless of mission length.

**`reset()`** clears all tiers. Called in `agent.py` when `"MISSION START"` appears in poll text.

---

### 4.2 `contracts.py` — ContractChecker

Evaluates 4 rules each tick against `/state` data. Returns alert strings injected into poll text before the LLM or WeightedPlanner sees it. Uses the same `aiohttp.ClientSession` as the rest of the agent — no new connections.

```python
class ContractChecker:
    def __init__(self, backend_url: str) -> None

    async def check(self, http_session: aiohttp.ClientSession, tick: int) -> list[str]
    # Returns list of alert strings (empty list if no violations)
```

**Four contracts (all respect the no-hidden-victims constraint):**

| # | Contract | Condition | Severity | Alert text |
|---|---|---|---|---|
| 1 | Coverage pace | `coverage_pct < (tick / 300) * 100` | WARNING | `⚠ CONTRACT: Coverage pace too slow — consider redistributing drones` |
| 2 | Idle drone | Any drone `status=IDLE` for `>15` ticks | CRITICAL | `⚠ CONTRACT: ALPHA-N idle 15+ ticks — must be assigned immediately` |
| 3 | High-score zone unassigned | Zone `Score > 1.5` unassigned for `>15` ticks | CRITICAL | `⚠ CONTRACT: Zone ZN (Score X.X) unassigned 15+ ticks — assign immediately` |
| 4 | Row gap | No active drone in a grid row for `>20` ticks | WARNING | `⚠ CONTRACT: Row N has no active drone — risk of missed cells` |

Contracts 2 and 3 are CRITICAL — the system prompt already instructs the agent to never leave drones idle and to prioritise high-score zones, so CRITICAL alerts reinforce existing instructions without adding new prompt sections.

`ContractChecker` maintains `idle_since: dict[str, int]` (drone_id → tick when it became idle) and `zone_unassigned_since: dict[str, int]` (zone_id → tick when it became unassigned) as instance state, updated each time `check()` is called.

---

### 4.3 `fallback.py` — WeightedPlanner

Replaces `_rule_based_assignments()` and `_execute_rule_based()` in `agent.py`. Parses all drone options from poll text and scores each option before assigning — no extra MCP calls.

```python
class WeightedPlanner:
    def assign(self, poll_text: str) -> list[tuple[str, str, str | None]]
    # [("assign", drone_id, zone_id) | ("return", drone_id, None)]
```

**Scoring formula** (all fields parsed from existing poll text):

```
score = (zone_score    × 3.0)
      + (1/transit     × 2.0)
      + (gap_row_bonus × 1.0)
      + (partial_bonus × 0.5)
```

| Field | Poll text source | Notes |
|---|---|---|
| `zone_score` | `Score: 2.1` | Higher = more likely survivors |
| `transit` | `Transit: 4 cells` | Inverted — closer = higher score |
| `gap_row_bonus` | `[GAP-ROW]` tag | +1.0 if present |
| `partial_bonus` | `[PARTIAL-resume]` tag | +0.5 if present |

Assignment is greedy best-first with a `claimed_zones` set to prevent two drones sharing a zone. Drones that exhaust all options (all zones claimed by earlier drones) are sent RTB.

Assignments are logged with `[SMART-FALLBACK]` tag (instead of current `[AUTO]`), enabling LLM-vs-fallback comparison in metrics — directly addresses judge feedback.

**Parallel execution:** `_execute_rule_based()` is replaced by:

```python
tasks = [session.call_tool(...) for action in actions]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

5 sequential MCP calls (~500ms each) → 1 parallel batch (~500ms total).

---

### 4.4 `agent.py` — Slim Orchestrator

Imports and wires the three modules. Tick loop becomes:

```python
# PHASE 1: POLL
poll_text = (await session.call_tool("get_idle_drones", {})).content[0].text

# PHASE 1.5: CONTRACT CHECK (inject alerts)
alerts = await self.contracts.check(http_session, tick)
if alerts:
    poll_text += "\n\n" + "\n".join(alerts)

# PHASE 2: EXECUTE
if is_trivial or not llm_active:
    actions = self.planner.assign(poll_text)
    await _parallel_execute(session, actions)
else:
    memory_block = self.memory.to_prompt_block()
    # ... LLM path unchanged, memory_block injected into HumanMessage
    new_events = self.memory.extract(messages, tick)
```

Methods removed from `agent.py`: `_extract_memory_events`, `_rule_based_assignments`, `_execute_rule_based`.

---

## 5. Group B — Stubs (implement after Group A)

### 5.1 `session_log.py` — JSONL Tick Logger + Cross-Mission Learning

#### Write path — per-tick logging

Appends one JSON line per tick to `mission_reports/YYYY-MM-DD-HH-MM.jsonl`:

```json
{
  "tick": 42,
  "coverage_pct": 38.0,
  "drones": {
    "ALPHA-1": {"battery": 62, "zone": "Z4", "status": "scanning", "cells_moved": 18}
  },
  "events": ["Survivor at (3,7) — P1-CRITICAL"],
  "decision": {"type": "LLM", "assignments": [["ALPHA-1", "Z4"]], "tokens": 340},
  "contract_alerts": ["⚠ CONTRACT: Coverage pace too slow"],
  "errors": ["zone already IN_PROGRESS: Z2"]
}
```

Agent calls `/export-mission` endpoint on `MISSION COMPLETE`. A new `POST /export-mission` endpoint in `backend/server.py` writes the final summary JSON alongside the JSONL file.

#### Read path — cross-mission learning

At mission start, `session_log.py` reads the last 5 JSONL files from `mission_reports/` and computes aggregate insights. These are injected as a `=== HISTORICAL INTEL ===` block into the system prompt, giving the agent genuine cross-mission learning without any model fine-tuning.

**What is learned and how it is used:**

| Pattern extracted | How it helps the next mission |
|---|---|
| Avg actual battery drain per zone | Calibrate RTB timing — if drones consistently drain 31% per zone, assign conservatively |
| Drone idle latency (ticks between idle and assignment) | Self-awareness metric — if ALPHA-3 averages 4 ticks idle, agent prioritises assigning it faster |
| Zone split efficiency (split vs single-drone completion time) | Calibrate split threshold — if splits only save 15% time, raise Score threshold above 1.5 |
| LLM vs fallback decision quality (completion time per decision type) | Tune `_is_trivial()` — if LLM adds no benefit on 2-drone ticks, expand trivial detection |
| Contract violation frequency (which contracts fire most, at which tick) | Adjust early-mission strategy — if coverage pace fires every mission at tick ~45, spread drones earlier |
| Drone utilisation breakdown (% scanning / transiting / charging / idle per drone) | Identify systematic idle drones — if ALPHA-5 is idle 30% of ticks across missions, assignment strategy has a gap |
| Error frequency (zone conflicts, LLM no-action fallbacks) | Surface recurring failure modes — if "zone IN_PROGRESS" errors appear in 4/5 missions, zone conflict gate in `hooks.py` should be prioritised |
| Terrain-type detection rate (city/forest/flat survivors found ratio) | Pre-calibrate zone scores before Bayesian updates kick in |

**Constraint respected:** No victim locations or victim counts are read from logs. All patterns are aggregated across ticks and missions — the agent learns *how it operates*, not *where victims hide*.

**Example injected block at mission start:**

```
=== HISTORICAL INTEL (last 5 missions) ===
• Battery: avg drain 31% per zone — assign drones with >56% battery to avoid mid-zone RTB
• Zone splits: Score > 2.1 completed 40% faster when split (current threshold 1.5 — consider raising)
• LLM value: 3+ drone ticks resolved 18% faster with LLM; 1-2 drone ticks: no measurable difference
• Idle latency: ALPHA-3 averages 3.8 ticks idle before assignment — watch for idle contract
• Contracts: coverage pace fired in 4/5 missions at tick ~45 — spread drones across all rows at mission start
• Errors: "zone IN_PROGRESS" appeared in 3/5 missions — zone conflict pre-check recommended
=== END HISTORICAL INTEL ===
```

`load_insights(n=5) -> str` is the public method called by `agent.py` at mission start, returning the formatted block or an empty string if no prior missions exist.

### 5.2 `hooks.py` — Pre/PostToolUse Layer

Thin wrapper around `session.call_tool()`:

- **Pre-battery gate:** If `assign_scan_zone` called with drone battery < estimated zone cost + 5% reserve → auto-convert to `return_to_base` without LLM round-trip
- **Pre-zone conflict gate:** If zone already `IN_PROGRESS` → return early with descriptive error before MCP call
- **Post-assign hook:** Update `MissionMemory` tier 1 on successful assignment
- **Post-detect hook:** Immediately log tier 0 event on survivor detection (before `extract()` runs at tick end)

---

## 6. Implementation Order

1. Create `agent/fallback.py` — WeightedPlanner (pure parsing, no dependencies)
2. Create `agent/memory.py` — MissionMemory (no dependencies)
3. Create `agent/contracts.py` — ContractChecker (depends on `aiohttp`)
4. Refactor `agent/agent.py` — wire modules, add parallel execution, remove extracted methods
5. Create `agent/session_log.py` (write path + `load_insights()`) + `agent/hooks.py` stub
6. Add `POST /export-mission` endpoint to `backend/server.py`

---

## 7. Files Changed

| File | Change |
|------|--------|
| `agent/agent.py` | Refactor: remove 3 methods, wire MissionMemory + ContractChecker + WeightedPlanner |
| `agent/memory.py` | New: MissionMemory class |
| `agent/contracts.py` | New: ContractChecker class |
| `agent/fallback.py` | New: WeightedPlanner class |
| `agent/session_log.py` | New (Group B): JSONL write path + `load_insights()` read path |
| `agent/hooks.py` | New stub (Group B) |
| `backend/server.py` | Add `POST /export-mission` stub (Group B) |

No changes to `backend/mcp_tools.py`, `backend/simulation.py`, or any frontend files.

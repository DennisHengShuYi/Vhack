# Commander-Pilot Multi-Agent Architecture Design

**Date:** 2026-04-19  
**Status:** Approved for implementation  
**Scope:** Refactor `agent/agent.py` and `agent/contracts.py`; all other modules unchanged

---

## 1. Problem Statement

The current single-agent architecture has two root-cause defects:

**Think-Lock Bottleneck** — `self.llm.ainvoke(...)` is a blocking `await`. The entire agent loop freezes for 10–30 s while the LLM reasons about one drone. Any drone that finishes a zone during this window is "orphaned" — it cannot be detected or assigned until the current LLM call completes.

**City Zone Deprioritisation** — Two compounding causes:
1. `SYSTEM_PROMPT` instructs the LLM to "spread drones across grid rows," which overrides zone score ordering. City zones in the same row get skipped in favour of flat zones in uncovered rows.
2. The `_row_gaps` contract reinforces this by alerting whenever a grid row has no active drone, pressuring the LLM toward row-spread rather than score-first assignment.

The catch-up re-poll added previously treats the symptom (assigns orphaned drones rule-based after the LLM finishes) but does not fix the root cause.

---

## 2. Solution: Commander-Pilot Architecture

Replace the single sequential agent with **six concurrent asyncio tasks** — one Commander and five Pilots — coordinated through a shared in-memory Blackboard and asyncio events.

```
Backend (/state, MCP)
    ↓ poll every 0.5 s
Orchestrator  ──idle_events["ALPHA-N"].set()──→  Pilot-ALPHA-N  (wakes, reasons, assigns)
              ──commander_trigger.put(event)──→  Commander       (wakes, strategises, updates Blackboard)

Blackboard (shared dataclass, asyncio.Lock for zone_claims)
    ← Commander writes priority_map, posture, urgent_redirect
    → Pilots read on every wake; write zone_claims under lock
```

All six tasks run inside **one Python process** on the same asyncio event loop. No subprocesses, no network between agents, no serialisation overhead.

---

## 3. Components

### 3.1 Orchestrator (thin poller)

**Responsibility:** Poll the backend, detect state changes, fire events. Own the single shared MCP `ClientSession` and the single `aiohttp.ClientSession`. Spawn and monitor the six background tasks — restart any that raise an unhandled exception.

**Loop cadence:** every 0.5 s

**Detects and fires:**
| Event | Trigger condition | Target |
|-------|-------------------|--------|
| `idle_events["ALPHA-N"].set()` | Drone N appears in `get_idle_drones()` | Pilot-ALPHA-N |
| `commander_trigger.put("mission_start")` | `"MISSION START"` in poll text | Commander |
| `commander_trigger.put("survivor_found")` | new victim in `/state` vs last tick | Commander |
| `commander_trigger.put("lead_grounded")` | new GROUNDED lead in `/state` | Commander |
| `commander_trigger.put("battery_crisis")` | fleet avg battery < 40% | Commander |
| `commander_trigger.put("timer")` | every 30 s (asyncio periodic) | Commander |
| `commander_trigger.put("contract:<alert>")` | ContractChecker fires an alert | Commander |

**Owns:** `SessionLog` (calls `log_tick` each poll cycle), `ContractChecker` (checks each poll cycle).

**Does NOT own:** LLM, MissionMemory, WeightedPlanner, ToolHooks.

### 3.2 Commander (1 LLM agent)

**Responsibility:** Fleet-wide strategic reasoning. Produces a priority map and posture that all Pilots inherit. Judges see this as the strategic brain of the swarm.

**Wake condition:** `await commander_trigger.get()`

**Inputs on each wake:**
- Event type (mission_start / survivor_found / lead_grounded / battery_crisis / timer / contract alert)
- `GET /state` — full fleet state (zones, drones, leads, coverage)
- `MissionMemory.to_prompt_block()` — tiered critical/important/routine events
- Historical intel string (injected on `mission_start` only, then cleared)

**LLM output (parsed):**
- `priority_map`: `{zone_id: float}` — overrides terrain defaults
- `posture`: one of `SPREAD | CONVERGE | LEAD_CHASE | RTB_CAUTIOUS`
- `urgent_redirect`: `(x, y, reason)` or `None` — forces nearest-Pilot to investigate

**Writes to Blackboard** (no lock needed — Commander is the sole writer of strategic fields).

**Logs** a `COMMANDER BRIEF` entry to the frontend timeline (judges see strategic reasoning).

**Fallback:** if LLM fails, keeps existing Blackboard state (stale but valid priorities).

**Owns:** `MissionMemory` (reads for prompt; Pilots write to it via ToolHooks).

### 3.3 Pilot × 5 (one per drone)

**Responsibility:** Single-drone tactical reasoning. Wakes the instant its drone goes idle. Reasons about zone options guided by the Blackboard. Commits zone claim atomically. Executes MCP assignment.

**Wake condition:** `await idle_events["ALPHA-N"].wait()`

**Protocol on each wake:**
1. Read `Blackboard.priority_map` and `Blackboard.posture` — no lock needed (reading only)
2. Read `GET /state` for this drone's battery, location, assigned zone
3. Acquire `Blackboard.lock`, snapshot `zone_claims` into a local set, release lock immediately — reasoning happens entirely outside the lock
5. Build short tactical prompt: drone position, battery, posture, available zones sorted by priority_map weight, nearby leads/finds tags
6. Call LLM (~1–2 s with fast model) — output is `DECISION → <zone_id>: <reason>` plus a backup zone
7. Commit atomically:
   - Acquire `Blackboard.lock`
   - If primary zone not in `zone_claims` → commit primary
   - Else if backup zone not in `zone_claims` → commit backup
   - Else → RTB (no zones available)
   - Release lock immediately (no await inside lock)
8. Run `ToolHooks.pre_assign()` — battery gate + zone conflict gate
9. Call `assign_scan_zone` MCP tool via shared `ClientSession`
10. Run `ToolHooks.post_assign()` — writes tier 1 to MissionMemory
11. Post to frontend log tagged with drone_id (e.g. `[ALPHA-1] Assigned Z3 — city zone, score 7.8`)
12. Clear `idle_events["ALPHA-N"]`, go back to waiting

**Fallback:** if LLM fails (timeout / API error), `WeightedPlanner.assign()` handles this drone only. Other Pilots are completely unaffected.

**Owns (one instance per Pilot):** `WeightedPlanner`, `ToolHooks`.

### 3.4 Blackboard (shared in-memory state)

```python
@dataclass
class ZoneClaim:
    drone_id: str
    committed_at_tick: int
    expires_at_tick: int   # safety expiry — 60 ticks (~42 s)

@dataclass
class Blackboard:
    # Commander writes; Pilots read (no lock needed for reads)
    priority_map: dict[str, float]        # zone_id → weight; initialised from terrain scores
    posture: str                           # SPREAD | CONVERGE | LEAD_CHASE | RTB_CAUTIOUS
    urgent_redirect: tuple | None         # (x, y, reason) — Pilot sets to None after consuming
    updated_at_tick: int

    # Pilots write and read under lock
    zone_claims: dict[str, ZoneClaim]    # COMMITTED only — no PENDING
    lock: asyncio.Lock
```

**Claim semantics:** only COMMITTED claims exist. A Pilot reads all unclaimed zones freely, reasons, then commits atomically. If two Pilots want the same zone, one commits first; the other falls back to its backup choice (already decided during reasoning — no second LLM call).

**Claim expiry:** claims expire after 60 ticks. Orchestrator scrubs expired claims each poll cycle. This prevents leaked claims if a drone fails mid-zone.

---

## 4. Event Transport

All events are plain asyncio primitives — Python objects passed by reference at task spawn time. No serialisation, no broker, no network.

| Primitive | Used for | Why |
|-----------|----------|-----|
| `asyncio.Event` per drone | Orchestrator → Pilot | Simple flag; Pilot blocks on `.wait()`, Orchestrator calls `.set()` |
| `asyncio.Queue` | Orchestrator → Commander | Queue (not Event) because Orchestrator needs to pass event type + payload, not just a signal |

Queue items are dicts: `{"event": "survivor_found", "tick": 47, "payload": {...}}`. Commander reads the event type and payload to tailor its LLM prompt. `mission_start` items include `"historical_intel"` key with the SessionLog insights string.

---

## 5. Zone Claim Concurrency

**asyncio threading model:** single OS thread, one coroutine active at a time. Context switches occur only at `await` points.

**Why a lock is still needed:** the check-then-write sequence `(is zone free?) → (write claim)` is not atomic if an `await` exists between the two steps. Without a lock, two Pilots waking simultaneously could both read "Z0 is free" then both write a claim.

**Lock held for:** microseconds (pure dict read/write, no `await` inside the lock block).  
**Lock NOT held during:** LLM reasoning (~1–2 s). Pilots never block each other on reasoning.

**Reason-first protocol (no PENDING claims):**
- Pilots reason about ALL non-COMMITTED zones simultaneously
- Commit is the only serialised step
- If primary zone is taken at commit time, Pilot uses its backup from the same reasoning — no retry LLM call

This is simpler than TCC/2PC and correct for a single-process asyncio system. TCC/2PC would be appropriate if Pilots ran in separate processes with network communication.

---

## 6. Helper Module Decisions

| Module | Decision | Change |
|--------|----------|--------|
| `hooks.py` | Keep, no code changes | Owned by each Pilot (one instance per Pilot) |
| `contracts.py` | Partial refactor | Remove `_idle_drones` and `_row_gaps`; remaining alerts fire `commander_trigger` instead of injecting into poll text |
| `memory.py` | Keep, no code changes | Owned by Commander; Pilots write to it via ToolHooks (shared object) |
| `session_log.py` | Keep, no code changes | Owned by Orchestrator; historical intel passed to Commander on mission_start |
| `fallback.py` | Keep, no code changes | Owned by each Pilot (per-Pilot fallback on LLM failure) |
| `history.py` (backend) | Keep, no changes | Backend endpoint unchanged |

**Removed contracts:**
- `_idle_drones` — Commander-Pilot architecture inherently prevents idle drones (Pilots wake immediately on idle event). Contract is no longer meaningful.
- `_row_gaps` — "ensure one drone per grid row" directly conflicts with city-first zone scoring and was a root cause of the city deprioritisation bug.

**Self-evolution (cross-mission learning):** preserved. `SessionLog.load_insights()` called by Orchestrator at mission start; result string passed as payload in `commander_trigger.put("mission_start", historical_intel=...)`. Commander injects it into its opening LLM prompt. Pilots inherit the evolved strategy through the Blackboard.

---

## 7. SYSTEM_PROMPT Changes

**Commander prompt:** replace current monolithic SYSTEM_PROMPT with a strategic-only prompt. Remove "spread drones across grid rows" instruction entirely. Commander reasons about fleet-wide posture, zone scores, coverage gaps, battery health, and leads.

**Pilot prompt:** short tactical prompt per wake. Format:
```
You are Pilot for ALPHA-N at (x, y). Battery: B%.
Posture: <SPREAD|CONVERGE|...>
Available zones (by priority):
  Z0 — score 8.5 (city, 12 city cells) | transit 4 | [LEAD-NEARBY]
  Z3 — score 7.8 (city, 9 city cells)  | transit 6
  Z1 — score 6.2 (forest)              | transit 2 | [PARTIAL-resume]
Write: DECISION → <zone_id>: <reason in ≤10 words>
       BACKUP   → <zone_id>: <reason in ≤10 words>
```

Pilot prompt has no grid layout, no posture decision, no fleet overview — just one drone's tactical choice.

---

## 8. Model Change

Switch from `gpt-5-nano` (10–30 s per call, 30–40 s cold start) to `gpt-4o-mini` (1–3 s per call, 2–4 s cold start). Set `LLM_MODEL=gpt-4o-mini` in `.env`.

Commander can use the same model — its strategic brief is infrequent so latency matters less.  
Pilots benefit most from the speed reduction — 1–2 s pilot reasoning vs 10–30 s today.

---

## 9. Error Handling

| Failure | Behaviour |
|---------|-----------|
| Pilot LLM timeout / error | That Pilot falls back to `WeightedPlanner` for its drone; other Pilots unaffected |
| Commander LLM failure | Blackboard keeps existing priority_map; Pilots use stale but valid data |
| Pilot task crashes | Orchestrator catches exception, logs to stderr, relaunches Pilot task |
| Commander task crashes | Orchestrator relaunches Commander; Blackboard state preserved |
| Stale zone claim (drone failed mid-zone) | Orchestrator scrubs claims where `expires_at_tick < current_tick` each poll cycle |
| MCP tool call error | Each Pilot handles its own MCP errors independently; other Pilots unaffected |

---

## 10. What Is NOT Changing

- `backend/` — no changes to FastAPI, FastMCP, SimulationState, simulation engine, REST endpoints
- `frontend/` — no changes; drone_id tag on log entries is additive (existing log rendering handles it)
- `agent/fallback.py`, `agent/memory.py`, `agent/session_log.py`, `agent/hooks.py` — no code changes
- `backend/history.py` — no changes
- MCP tool set — no new tools needed; existing tools (`get_idle_drones`, `assign_scan_zone`, `return_to_base`, `investigate_lead`, `get_pending_leads`) are sufficient

---

## 11. Files to Create / Modify

| File | Action | Summary |
|------|--------|---------|
| `agent/agent.py` | Major refactor | Replace `AgentOrchestrator` with `Blackboard`, `Commander`, `Pilot`, thin `AgentOrchestrator` |
| `agent/contracts.py` | Partial edit | Remove `_idle_drones()` and `_row_gaps()` methods |
| `.env` / `.env.example` | Edit | Add `LLM_MODEL=gpt-4o-mini` |

No new files required. No backend changes.

---

## 12. Success Criteria

- All 5 drones assigned within 3 s of going idle (vs 10–30 s today)
- No drone orphaned for more than one poll cycle (0.5 s)
- City zones (highest zone score) assigned before flat zones in all observed missions
- Frontend timeline shows parallel per-drone reasoning streams
- Commander BRIEF appears as a distinct timeline event on mission start and on major events
- Historical intel loaded and visible in Commander's first brief log entry
- WeightedPlanner fallback activates per-drone on LLM error without affecting other drones

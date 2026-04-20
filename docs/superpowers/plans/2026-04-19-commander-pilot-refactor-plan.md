# Commander-Pilot Multi-Agent Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single blocking-LLM agent loop with a Commander + 5 Pilot asyncio task architecture that eliminates drone orphaning, prioritises city zones, and keeps judge-visible reasoning for every drone.

**Architecture:** One thin Orchestrator polls the backend and fires asyncio events. One Commander LLM agent updates a shared Blackboard (priority map + posture). Five Pilot LLM agents wake instantly when their drone goes idle, read the Blackboard, reason independently, commit a zone claim atomically, and execute the MCP assignment.

**Tech Stack:** Python asyncio, LangChain `ChatOpenAI`, MCP `ClientSession`, aiohttp, `gpt-4o-mini`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `agent/agent.py` | Major refactor | `ZoneClaim`, `Blackboard`, `Commander`, `Pilot`, slim `AgentOrchestrator` |
| `agent/contracts.py` | Partial edit | Remove `_idle_drones()`, `_row_gaps()`, `ROW_ZONES` |
| `agent/tests/test_contracts.py` | Partial edit | Remove tests for the two removed methods |
| `agent/tests/test_blackboard.py` | Create | Unit tests for `Blackboard` claim/expiry logic |
| `agent/tests/test_commander.py` | Create | Unit tests for `Commander._parse_brief()` |
| `agent/tests/test_pilot_commit.py` | Create | Unit tests for `Pilot._commit_zone()` and `Pilot._parse_llm_decision()` |
| `.env.example` | Edit | Set `LLM_MODEL=gpt-4o-mini` |

**Unchanged:** `agent/fallback.py`, `agent/hooks.py`, `agent/memory.py`, `agent/session_log.py`, all of `backend/`, all of `frontend/`

---

## Task 1: Switch model to gpt-4o-mini

**Files:**
- Modify: `.env.example`
- Modify: `.env` (local only, not committed)
- Modify: `agent/agent.py` line ~199 (default model fallback)

- [ ] **Step 1: Update `.env.example`**

Open `.env.example` and change the `LLM_MODEL` line to:
```
LLM_MODEL=gpt-4o-mini
```

- [ ] **Step 2: Update your local `.env`**

In your local `.env` file, set:
```
LLM_MODEL=gpt-4o-mini
```

- [ ] **Step 3: Update default fallback in `agent/agent.py`**

Find these two lines (around line 199 and 217):
```python
self.llm = ChatOpenAI(model=model or "gpt-5-nano", temperature=0.3, streaming=True)
```
```python
"CLOUD": os.getenv("LLM_MODEL", "gpt-5-nano"),
```
Change both `"gpt-5-nano"` to `"gpt-4o-mini"`.

- [ ] **Step 4: Commit**

```bash
git add .env.example agent/agent.py
git commit -m "chore: switch default LLM model to gpt-4o-mini"
```

---

## Task 2: Refactor contracts.py — remove idle and row-gap contracts

**Files:**
- Modify: `agent/contracts.py`
- Modify: `agent/tests/test_contracts.py`

- [ ] **Step 1: Write a replacement test for reset() that uses a remaining contract**

In `agent/tests/test_contracts.py`, replace `test_reset_clears_counters` (it tested idle drone alerting which is being removed):

```python
def test_reset_clears_counters():
    checker = ContractChecker()
    # High-score zone unassigned for 16 ticks triggers alert
    zones = {"Z0": {"status": "UNSCANNED", "score": 2.8}}
    drones = [{"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z5", "is_active": True}]
    for t in range(1, 17):
        checker.check(_state(drones=drones, zones=zones), tick=t)
    checker.reset()
    # After reset, counter clears — no alert on next tick
    alerts = checker.check(_state(drones=drones, zones=zones), tick=17)
    assert not any("Z0" in a for a in alerts)
```

- [ ] **Step 2: Run existing tests to establish baseline**

```bash
cd "C:/Users/shaoxian04/Documents/VHack Project"
python -m pytest agent/tests/test_contracts.py -v
```

Expected: all tests pass (including the row_gap and idle tests — they still exist at this point).

- [ ] **Step 3: Remove row-gap and idle-drone tests from `test_contracts.py`**

Delete these test functions entirely:
- `test_idle_drone_alert_after_15_ticks`
- `test_idle_drone_no_alert_before_15_ticks`
- `test_row_gap_alert_after_20_ticks`
- `test_row_gap_no_alert_when_all_rows_covered`
- `test_inactive_drone_not_flagged_idle`

- [ ] **Step 4: Run tests — expect failures**

```bash
python -m pytest agent/tests/test_contracts.py -v
```

Expected: remaining tests should pass. If any fail, the `_state()` helper may need the `leads` key — add it:
```python
def _state(coverage=50.0, drones=None, zones=None):
    return {
        "stats": {"coverage_pct": coverage, "mission_active": True},
        "drones": drones or [
            {"id": "ALPHA-1", "status": "scanning", "assigned_zone_id": "Z0", "is_active": True},
            {"id": "ALPHA-2", "status": "scanning", "assigned_zone_id": "Z5", "is_active": True},
            {"id": "ALPHA-3", "status": "scanning", "assigned_zone_id": "Z9", "is_active": True},
        ],
        "zone": {"zones": zones or {
            "Z0": {"status": "IN_PROGRESS", "score": 2.5},
            "Z5": {"status": "IN_PROGRESS", "score": 1.2},
            "Z9": {"status": "IN_PROGRESS", "score": 0.8},
        }},
        "leads": [],
    }
```

- [ ] **Step 5: Remove `_idle_drones`, `_row_gaps`, and `ROW_ZONES` from `contracts.py`**

Delete the `ROW_ZONES` dict at the top of the file.

Delete the `IDLE_THRESHOLD = 15` constant.

Delete these methods from `ContractChecker`:
- `_idle_drones()`
- `_row_gaps()`

Also remove `self.idle_since` and `self.row_gap_since` from `__init__` and `reset()`:

```python
def __init__(self) -> None:
    self.zone_unassigned_since: dict[str, int] = {}
    self.lead_unaddressed_since: dict[str, int] = {}

def reset(self) -> None:
    self.zone_unassigned_since = {}
    self.lead_unaddressed_since = {}
```

Remove the two calls from `check()`:
```python
def check(self, state: dict, tick: int) -> list[str]:
    if not state.get("stats", {}).get("mission_active", False):
        return []
    alerts: list[str] = []
    alerts.extend(self._coverage_pace(state, tick))
    alerts.extend(self._high_score_zones(state, tick))
    alerts.extend(self._unaddressed_leads(state, tick))
    return alerts
```

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest agent/tests/test_contracts.py -v
```

Expected: all 6 remaining tests pass.

- [ ] **Step 7: Commit**

```bash
git add agent/contracts.py agent/tests/test_contracts.py
git commit -m "refactor: remove idle-drone and row-gap contracts — conflicts with city-first priority"
```

---

## Task 3: Add Blackboard and ZoneClaim dataclasses to agent.py

**Files:**
- Modify: `agent/agent.py` — add at the top, after imports
- Create: `agent/tests/test_blackboard.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_blackboard.py`:

```python
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.agent import Blackboard, ZoneClaim


def _make_board(claims=None, tick=10):
    return Blackboard(
        priority_map={"Z0": 8.5, "Z3": 7.8, "Z1": 6.2},
        posture="SPREAD",
        urgent_redirect=None,
        updated_at_tick=tick,
        tick=tick,
        zone_claims=claims or {},
        lock=asyncio.Lock(),
    )


def test_commit_zone_adds_claim():
    board = _make_board()

    async def _run():
        async with board.lock:
            board.zone_claims["Z0"] = ZoneClaim("ALPHA-1", 10, 70)

    asyncio.run(_run())
    assert "Z0" in board.zone_claims
    assert board.zone_claims["Z0"].drone_id == "ALPHA-1"
    assert board.zone_claims["Z0"].expires_at_tick == 70


def test_scrub_removes_expired_claims():
    board = _make_board(
        claims={"Z0": ZoneClaim("ALPHA-1", 5, 50)},  # expired at tick 50
        tick=100,
    )
    board.zone_claims = {
        z: c for z, c in board.zone_claims.items()
        if c.expires_at_tick > board.tick
    }
    assert "Z0" not in board.zone_claims


def test_scrub_keeps_active_claims():
    board = _make_board(
        claims={"Z3": ZoneClaim("ALPHA-2", 95, 155)},  # expires at 155, tick=100
        tick=100,
    )
    board.zone_claims = {
        z: c for z, c in board.zone_claims.items()
        if c.expires_at_tick > board.tick
    }
    assert "Z3" in board.zone_claims


def test_priority_map_readable_without_lock():
    board = _make_board()
    # No lock needed for reads — just verify values accessible
    assert board.priority_map["Z0"] == 8.5
    assert board.posture == "SPREAD"
    assert board.urgent_redirect is None
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
python -m pytest agent/tests/test_blackboard.py -v
```

Expected: `ImportError: cannot import name 'Blackboard' from 'agent.agent'`

- [ ] **Step 3: Add `ZoneClaim` and `Blackboard` to `agent/agent.py`**

Insert after the existing imports, before the `SYSTEM_PROMPT` constant:

```python
from dataclasses import dataclass, field

@dataclass
class ZoneClaim:
    drone_id: str
    committed_at_tick: int
    expires_at_tick: int


@dataclass
class Blackboard:
    priority_map: dict        # zone_id → float weight; Commander writes, Pilots read
    posture: str              # SPREAD | CONVERGE | LEAD_CHASE | RTB_CAUTIOUS
    urgent_redirect: tuple | None  # (x, y, reason) — Pilot sets to None after consuming
    updated_at_tick: int
    tick: int                 # current Orchestrator tick; updated each poll cycle
    zone_claims: dict         # zone_id → ZoneClaim (COMMITTED only, no PENDING)
    lock: asyncio.Lock
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest agent/tests/test_blackboard.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/agent.py agent/tests/test_blackboard.py
git commit -m "feat: add Blackboard and ZoneClaim dataclasses"
```

---

## Task 4: Add Commander class to agent.py

**Files:**
- Modify: `agent/agent.py` — add `Commander` class and `COMMANDER_SYSTEM_PROMPT`
- Create: `agent/tests/test_commander.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_commander.py`:

```python
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.agent import Commander, Blackboard, ZoneClaim
from agent.memory import MissionMemory


def _make_commander():
    board = Blackboard(
        priority_map={},
        posture="SPREAD",
        urgent_redirect=None,
        updated_at_tick=0,
        tick=0,
        zone_claims={},
        lock=asyncio.Lock(),
    )
    mem = MissionMemory()
    return Commander(board, mem, llm=None, http_session=None, backend_url="")


def test_parse_brief_extracts_priority_map():
    c = _make_commander()
    text = "POSTURE: CONVERGE\nPRIORITY: Z0=8.5, Z3=7.8, Z1=6.2\nBRIEF: focus city zones"
    pmap, posture, redirect = c._parse_brief(text)
    assert pmap == {"Z0": 8.5, "Z3": 7.8, "Z1": 6.2}


def test_parse_brief_extracts_posture():
    c = _make_commander()
    _, posture, _ = c._parse_brief("POSTURE: LEAD_CHASE\nPRIORITY: Z0=5.0")
    assert posture == "LEAD_CHASE"


def test_parse_brief_defaults_posture_to_spread():
    c = _make_commander()
    _, posture, _ = c._parse_brief("PRIORITY: Z0=5.0")
    assert posture == "SPREAD"


def test_parse_brief_extracts_urgent_redirect():
    c = _make_commander()
    text = "POSTURE: LEAD_CHASE\nREDIRECT: (7, 3): critical survivor lead\nPRIORITY: Z0=5.0"
    _, posture, redirect = c._parse_brief(text)
    assert posture == "LEAD_CHASE"
    assert redirect == (7, 3, "critical survivor lead")


def test_parse_brief_no_redirect_returns_none():
    c = _make_commander()
    _, _, redirect = c._parse_brief("POSTURE: SPREAD\nPRIORITY: Z0=5.0")
    assert redirect is None


def test_parse_brief_updates_blackboard():
    c = _make_commander()
    text = "POSTURE: CONVERGE\nPRIORITY: Z0=9.0, Z5=3.0"
    pmap, posture, redirect = c._parse_brief(text)
    # Simulate what _handle does
    c.blackboard.priority_map = pmap
    c.blackboard.posture = posture
    c.blackboard.urgent_redirect = redirect
    assert c.blackboard.priority_map["Z0"] == 9.0
    assert c.blackboard.posture == "CONVERGE"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
python -m pytest agent/tests/test_commander.py -v
```

Expected: `ImportError: cannot import name 'Commander' from 'agent.agent'`

- [ ] **Step 3: Add `COMMANDER_SYSTEM_PROMPT` and `Commander` class to `agent/agent.py`**

Insert after the `Blackboard` dataclass:

```python
COMMANDER_SYSTEM_PROMPT = """You are SENTINEL Commander — strategic brain of the 5-drone rescue swarm.

Your job: assess the full fleet state and set priorities that all Pilot agents will follow.

Output EXACTLY this format (all four lines required):
POSTURE: <SPREAD|CONVERGE|LEAD_CHASE|RTB_CAUTIOUS>
PRIORITY: <Z0=X.X, Z1=X.X, Z2=X.X, ...>  (list every zone; city zones get 7-10, forest 4-6, flat 1-3)
REDIRECT: (<x>, <y>): <reason>  (omit this line entirely if no urgent redirect)
BRIEF: <1-2 sentences on current mission state and what Pilots should focus on>

Rules:
- City terrain zones ALWAYS get higher weight than flat zones regardless of distance
- LEAD_CHASE posture when a GROUNDED CRITICAL lead exists
- CONVERGE when coverage > 50% — focus on highest remaining scores
- RTB_CAUTIOUS when fleet avg battery < 40%
- SPREAD at mission start — distribute across grid
- Never include "spread across rows" logic — zone score is the only priority signal
"""


class Commander:

    def __init__(self, blackboard: Blackboard, memory, llm, http_session, backend_url: str):
        self.blackboard = blackboard
        self.memory = memory
        self.llm = llm
        self.http_session = http_session
        self.backend_url = backend_url

    async def run(self, trigger_queue: asyncio.Queue) -> None:
        """Main Commander loop — wakes on trigger_queue events."""
        while True:
            event = await trigger_queue.get()
            try:
                await self._handle(event)
            except Exception as e:
                print(f"[COMMANDER] Error handling {event.get('event')}: {e}", file=sys.stderr)

    async def _handle(self, event: dict) -> None:
        event_type = event.get("event", "timer")
        tick = event.get("tick", 0)
        historical_intel = event.get("historical_intel", "")

        try:
            resp = await self.http_session.get(f"{self.backend_url}/state")
            state = await resp.json()
        except Exception as e:
            print(f"[COMMANDER] State fetch failed: {e}", file=sys.stderr)
            return  # keep existing blackboard — stale but valid

        memory_block = self.memory.to_prompt_block()
        hist_block = f"\n{historical_intel}\n" if historical_intel else ""
        event_line = f"EVENT: {event_type.upper()} at tick {tick}"
        if event.get("payload"):
            event_line += f" — {event['payload']}"

        prompt = (
            f"{hist_block}"
            f"{event_line}\n\n"
            f"=== FLEET STATE ===\n{self._format_state(state)}\n"
            f"{memory_block}"
        )

        if self.llm is None:
            return

        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            response = await self.llm.ainvoke([
                SystemMessage(content=COMMANDER_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            print(f"[COMMANDER] LLM failed: {e}", file=sys.stderr)
            return

        priority_map, posture, urgent_redirect = self._parse_brief(text)
        if priority_map:
            self.blackboard.priority_map = priority_map
        self.blackboard.posture = posture
        self.blackboard.urgent_redirect = urgent_redirect
        self.blackboard.updated_at_tick = tick

        await self._broadcast(f"[COMMANDER BRIEF | tick={tick} | {event_type}] Posture={posture}\n{text}")
        await self._emit_timeline(tick, event_type, posture, len(priority_map))

    def _parse_brief(self, text: str) -> tuple[dict, str, tuple | None]:
        import re
        priority_map: dict[str, float] = {}
        posture = "SPREAD"
        urgent_redirect = None

        for m in re.finditer(r'(Z\d+)\s*=\s*([\d.]+)', text):
            priority_map[m.group(1)] = float(m.group(2))

        m = re.search(r'POSTURE\s*[:\→]\s*(SPREAD|CONVERGE|LEAD_CHASE|RTB_CAUTIOUS)', text, re.IGNORECASE)
        if m:
            posture = m.group(1).upper()

        m = re.search(r'REDIRECT\s*[:\→]?\s*\((\d+)\s*,\s*(\d+)\)\s*[:\-]?\s*(.+)', text)
        if m:
            urgent_redirect = (int(m.group(1)), int(m.group(2)), m.group(3).strip())

        return priority_map, posture, urgent_redirect

    def _format_state(self, state: dict) -> str:
        lines = []
        zones = state.get("zone", {}).get("zones", {})
        for zid, zone in sorted(zones.items()):
            score = zone.get("score", 0)
            status = zone.get("status", "")
            terrain = zone.get("terrain_counts", {})
            lines.append(f"  {zid}: score={score:.1f} status={status} terrain={terrain}")
        drones = state.get("drones", [])
        for d in drones:
            if d.get("is_active", True):
                lines.append(
                    f"  {d['id']}: battery={d.get('battery', 0):.0f}% "
                    f"zone={d.get('assigned_zone_id', 'None')} status={d.get('status', '')}"
                )
        leads = state.get("leads", [])
        for lead in leads:
            if lead.get("status") in ("GROUNDED", "PENDING_GROUND"):
                lines.append(
                    f"  LEAD {lead.get('id')}: ({lead.get('x')},{lead.get('y')}) "
                    f"urgency={lead.get('urgency')}"
                )
        drones_active = [d for d in drones if d.get("is_active", True)]
        if drones_active:
            avg_bat = sum(d.get("battery", 0) for d in drones_active) / len(drones_active)
            lines.append(f"  Fleet avg battery: {avg_bat:.0f}%")
        return "\n".join(lines)

    async def _broadcast(self, msg: str) -> None:
        try:
            await self.http_session.post(
                f"{self.backend_url}/log", params={"text": msg, "level": "AI"}
            )
        except Exception:
            pass

    async def _emit_timeline(self, tick: int, event_type: str, posture: str, zone_count: int) -> None:
        import json as _json
        try:
            await self.http_session.post(
                f"{self.backend_url}/timeline",
                params={
                    "tick": tick, "kind": "DECISION", "brain": "CLOUD", "duration_ms": 0,
                    "payload": _json.dumps({
                        "type": "COMMANDER_BRIEF", "trigger": event_type,
                        "posture": posture, "zones_updated": zone_count,
                    }),
                }
            )
        except Exception:
            pass
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest agent/tests/test_commander.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/agent.py agent/tests/test_commander.py
git commit -m "feat: add Commander class with strategic LLM brief and Blackboard updates"
```

---

## Task 5: Add Pilot class to agent.py

**Files:**
- Modify: `agent/agent.py` — add `PILOT_SYSTEM_PROMPT` and `Pilot` class
- Create: `agent/tests/test_pilot_commit.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_pilot_commit.py`:

```python
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from agent.agent import Blackboard, ZoneClaim, Pilot
from agent.memory import MissionMemory


def _make_board(claims=None, tick=10, priority_map=None):
    return Blackboard(
        priority_map=priority_map or {"Z0": 8.5, "Z3": 7.8, "Z1": 6.2},
        posture="SPREAD",
        urgent_redirect=None,
        updated_at_tick=tick,
        tick=tick,
        zone_claims=claims or {},
        lock=asyncio.Lock(),
    )


def _make_pilot(drone_id="ALPHA-1", board=None):
    board = board or _make_board()
    mem = MissionMemory()
    return Pilot(drone_id, board, mem, llm=None, mcp_session=None,
                 http_session=None, backend_url="")


# ── _commit_zone tests ────────────────────────────────────────────────────────

def test_commit_primary_zone():
    pilot = _make_pilot()
    result = asyncio.run(pilot._commit_zone("Z0", "Z3"))
    assert result == "Z0"
    assert "Z0" in pilot.blackboard.zone_claims
    assert pilot.blackboard.zone_claims["Z0"].drone_id == "ALPHA-1"
    assert pilot.blackboard.zone_claims["Z0"].expires_at_tick == 70  # tick=10 + 60


def test_commit_falls_back_to_backup_when_primary_taken():
    board = _make_board(claims={"Z0": ZoneClaim("ALPHA-2", 10, 70)})
    pilot = _make_pilot(board=board)
    result = asyncio.run(pilot._commit_zone("Z0", "Z3"))
    assert result == "Z3"
    assert "Z3" in pilot.blackboard.zone_claims
    assert "Z0" in pilot.blackboard.zone_claims  # ALPHA-2's claim untouched


def test_commit_returns_none_when_both_taken():
    board = _make_board(claims={
        "Z0": ZoneClaim("ALPHA-2", 10, 70),
        "Z3": ZoneClaim("ALPHA-3", 10, 70),
    })
    pilot = _make_pilot(board=board)
    result = asyncio.run(pilot._commit_zone("Z0", "Z3"))
    assert result is None


def test_commit_with_no_backup():
    board = _make_board(claims={"Z0": ZoneClaim("ALPHA-2", 10, 70)})
    pilot = _make_pilot(board=board)
    result = asyncio.run(pilot._commit_zone("Z0", None))
    assert result is None


# ── _parse_llm_decision tests ─────────────────────────────────────────────────

def test_parse_decision_standard_arrow():
    pilot = _make_pilot()
    primary, backup = pilot._parse_llm_decision(
        "DECISION → Z0: city zone highest score\nBACKUP → Z3: second city zone"
    )
    assert primary == "Z0"
    assert backup == "Z3"


def test_parse_decision_space_only_separator():
    pilot = _make_pilot()
    primary, backup = pilot._parse_llm_decision(
        "DECISION Z5: forest zone\nBACKUP Z1: partial resume"
    )
    assert primary == "Z5"
    assert backup == "Z1"


def test_parse_decision_rtb():
    pilot = _make_pilot()
    primary, backup = pilot._parse_llm_decision("DECISION → RTB: battery critical")
    assert primary == "RTB"
    assert backup is None


def test_parse_decision_missing_backup():
    pilot = _make_pilot()
    primary, backup = pilot._parse_llm_decision("DECISION → Z2: only option")
    assert primary == "Z2"
    assert backup is None
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
python -m pytest agent/tests/test_pilot_commit.py -v
```

Expected: `ImportError: cannot import name 'Pilot' from 'agent.agent'`

- [ ] **Step 3: Add `PILOT_SYSTEM_PROMPT` and `Pilot` class to `agent/agent.py`**

Insert after the `Commander` class:

```python
PILOT_SYSTEM_PROMPT = """You are a Pilot agent for an autonomous rescue drone in a search-and-rescue mission.

Your job: choose the best available zone for your specific drone.

Output EXACTLY this format:
DECISION → <zone_id>: <reason in ≤10 words>
BACKUP → <zone_id>: <reason in ≤10 words>

If battery is critical (< 35%), write:
DECISION → RTB: battery critical

Rules:
- DECISION and BACKUP must be different zones
- Higher priority score = more likely survivors — always prefer it
- City terrain zones have highest survivor probability
- Follow the stated posture
- Never pick a zone not listed in Available zones
"""


class Pilot:

    def __init__(
        self,
        drone_id: str,
        blackboard: Blackboard,
        memory,
        llm,
        mcp_session,
        http_session,
        backend_url: str,
    ):
        self.drone_id = drone_id
        self.blackboard = blackboard
        self.memory = memory
        self.llm = llm
        self.mcp_session = mcp_session
        self.http_session = http_session
        self.backend_url = backend_url
        self.hooks = ToolHooks(memory)
        self.planner = WeightedPlanner()

    async def run(self, idle_event: asyncio.Event) -> None:
        """Main Pilot loop — wakes whenever its drone goes idle."""
        while True:
            await idle_event.wait()
            idle_event.clear()
            try:
                await self._handle_idle()
            except Exception as e:
                print(f"[PILOT-{self.drone_id}] Error: {e}", file=sys.stderr)

    async def _handle_idle(self) -> None:
        tick = self.blackboard.tick

        # Snapshot committed claims — brief lock, no await inside
        async with self.blackboard.lock:
            taken: set[str] = set(self.blackboard.zone_claims.keys())

        # Fetch full state for hook validation and prompt building
        try:
            resp = await self.http_session.get(f"{self.backend_url}/state")
            state = await resp.json()
        except Exception:
            state = {}

        # Fetch idle drones poll text for zone options
        try:
            poll_result = await self.mcp_session.call_tool("get_idle_drones", {})
            poll_text = poll_result.content[0].text if poll_result.content else ""
        except Exception:
            poll_text = ""

        if not poll_text or "NO_IDLE_DRONES" in poll_text:
            return

        # Check urgent_redirect from Commander — consume if this drone is nearest
        redirect = self.blackboard.urgent_redirect
        if redirect:
            drone_data = next((d for d in state.get("drones", []) if d["id"] == self.drone_id), {})
            x, y, reason = redirect
            dist = abs(drone_data.get("x", 0) - x) + abs(drone_data.get("y", 0) - y)
            if dist <= 8 and self.hooks.pre_investigate_lead(self.drone_id, x, y, state):
                self.blackboard.urgent_redirect = None
                try:
                    result = await self.mcp_session.call_tool(
                        "investigate_lead", {"drone_id": self.drone_id, "x": x, "y": y, "reason": reason}
                    )
                    msg = result.content[0].text if result.content else "done"
                    await self._broadcast(f"[PILOT-{self.drone_id}] REDIRECT→({x},{y}): {msg[:80]}")
                except Exception as e:
                    print(f"[PILOT-{self.drone_id}] investigate error: {e}", file=sys.stderr)
                return

        # Build zone options for prompt
        available = self._format_zones(poll_text, taken)
        if not available:
            await self._rtb(state)
            return

        drone_data = next((d for d in state.get("drones", []) if d["id"] == self.drone_id), {})
        battery = drone_data.get("battery", 100.0)

        # LLM reasoning or rule-based fallback
        if self.llm:
            prompt = (
                f"Drone: {self.drone_id} | Battery: {battery:.0f}% | "
                f"Posture: {self.blackboard.posture}\n"
                f"Available zones (by priority):\n{available}"
            )
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                response = await self.llm.ainvoke([
                    SystemMessage(content=PILOT_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])
                text = response.content if hasattr(response, "content") else str(response)
                primary, backup = self._parse_llm_decision(text)
                await self._broadcast(
                    f"[PILOT-{self.drone_id}] Reasoning:\n{text}"
                )
            except Exception as e:
                print(f"[PILOT-{self.drone_id}] LLM failed, using fallback: {e}", file=sys.stderr)
                primary, backup = self._fallback_decision(poll_text, taken)
        else:
            primary, backup = self._fallback_decision(poll_text, taken)

        if primary == "RTB" or primary is None:
            await self._rtb(state)
            return

        # Atomic commit
        committed = await self._commit_zone(primary, backup)
        if committed is None:
            await self._rtb(state)
            return

        # Pre-hook validation (battery gate, zone conflict gate)
        validated = self.hooks.pre_assign(self.drone_id, committed, state)
        if validated is None:
            async with self.blackboard.lock:
                self.blackboard.zone_claims.pop(committed, None)
            await self._rtb(state)
            return

        # Execute MCP assignment
        try:
            result = await self.mcp_session.call_tool(
                "assign_scan_zone", {"drone_id": self.drone_id, "zone_id": committed}
            )
            msg = result.content[0].text if result.content else "done"
            await self._broadcast(f"[PILOT-{self.drone_id}] ✓ Assigned {committed}: {msg[:80]}")
            self.hooks.post_assign(self.drone_id, committed, msg, tick)
            if "survivor" in msg.lower() and ("found" in msg.lower() or "detected" in msg.lower()):
                self.hooks.post_detect(self.drone_id, msg, tick)
        except Exception as e:
            print(f"[PILOT-{self.drone_id}] MCP assign error: {e}", file=sys.stderr)
            async with self.blackboard.lock:
                self.blackboard.zone_claims.pop(committed, None)

    async def _commit_zone(self, primary: str, backup: str | None) -> str | None:
        """Atomically commit primary zone; fall back to backup; return None if both taken."""
        async with self.blackboard.lock:
            for zone in [primary, backup]:
                if zone and zone not in self.blackboard.zone_claims:
                    self.blackboard.zone_claims[zone] = ZoneClaim(
                        drone_id=self.drone_id,
                        committed_at_tick=self.blackboard.tick,
                        expires_at_tick=self.blackboard.tick + 60,
                    )
                    return zone
        return None

    def _parse_llm_decision(self, text: str) -> tuple[str | None, str | None]:
        import re
        primary = backup = None
        # Optional separator: → >= :- or just space
        m = re.search(r'DECISION\s*[→>=:\-]?\s+(\w+)', text, re.IGNORECASE)
        if m:
            primary = m.group(1).upper()
        m = re.search(r'BACKUP\s*[→>=:\-]?\s+(\w+)', text, re.IGNORECASE)
        if m:
            backup = m.group(1).upper()
        return primary, backup

    def _fallback_decision(self, poll_text: str, taken: set) -> tuple[str | None, str | None]:
        actions = self.planner.assign(poll_text)
        for action in actions:
            if action[0] == "return" and action[1] == self.drone_id:
                return "RTB", None
            if action[0] == "assign" and action[1] == self.drone_id and action[2] not in taken:
                return action[2], None
        return None, None

    def _format_zones(self, poll_text: str, taken: set) -> str:
        """Build a priority-sorted zone list for the Pilot LLM prompt."""
        options = self.planner._parse_options(poll_text)
        drone_opts = options.get(self.drone_id, [])
        lines = []
        for opt in drone_opts:
            if opt.get("rtb"):
                continue
            zone = opt["zone"]
            if zone in taken:
                continue
            weight = self.blackboard.priority_map.get(zone, opt["score"])
            tags = []
            if opt.get("gap_row"):
                tags.append("[GAP-ROW]")
            if opt.get("partial"):
                tags.append("[PARTIAL-resume]")
            if opt.get("adjacent_to_lead"):
                tags.append("[LEAD-NEARBY]")
            if opt.get("adjacent_to_finds"):
                tags.append("[FIND-NEARBY]")
            lines.append((weight, f"  {zone} — priority={weight:.1f} score={opt['score']:.2f} transit={opt['transit']} {' '.join(tags)}".rstrip()))
        lines.sort(reverse=True)
        return "\n".join(line for _, line in lines)

    async def _rtb(self, state: dict) -> None:
        try:
            result = await self.mcp_session.call_tool("return_to_base", {"drone_id": self.drone_id})
            msg = result.content[0].text if result.content else "done"
            await self._broadcast(f"[PILOT-{self.drone_id}] RTB: {msg[:60]}")
        except Exception as e:
            print(f"[PILOT-{self.drone_id}] RTB error: {e}", file=sys.stderr)

    async def _broadcast(self, msg: str) -> None:
        try:
            await self.http_session.post(
                f"{self.backend_url}/log", params={"text": msg, "level": "AI"}
            )
        except Exception:
            pass
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest agent/tests/test_pilot_commit.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Run all agent tests to catch regressions**

```bash
python -m pytest agent/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add agent/agent.py agent/tests/test_pilot_commit.py
git commit -m "feat: add Pilot class with parallel async reasoning and atomic zone commit"
```

---

## Task 6: Replace AgentOrchestrator with thin poller

**Files:**
- Modify: `agent/agent.py` — rewrite `AgentOrchestrator` class

This task replaces `run_mission_loop` with a thin event-routing loop that spawns Commander and Pilot tasks. The old `_parse_llm_decisions`, `_parallel_execute`, `_must_skip_llm`, `_next_available_zone`, `_recall_all_drones`, `_execute_rule_based` methods are all removed — their responsibilities are now in `Pilot` and `Commander`.

- [ ] **Step 1: Replace `AgentOrchestrator` class in `agent/agent.py`**

Delete the entire existing `AgentOrchestrator` class and replace with:

```python
class AgentOrchestrator:

    def __init__(self, server_script_path: str):
        self.server_script_path = server_script_path
        self.backend_url = "http://127.0.0.1:8000"
        self.memory = MissionMemory()
        self.contracts = ContractChecker()
        self.session_log = SessionLog()

        openai_key = os.getenv("OPENAI_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        provider = os.getenv("ACTIVE_PROVIDER", "").upper()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")

        if provider == "GEMINI" or (not provider and gemini_key and not (openai_key or "").strip()):
            if gemini_key:
                self.llm = ChatOpenAI(
                    model=model if model != "gpt-4o-mini" else "gemini-2.5-flash",
                    openai_api_key=gemini_key,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    temperature=0,
                    streaming=True,
                )
                print(f"[SENTINEL] Gemini provider: {model}", file=sys.stderr)
            else:
                self.llm = None
                print("[SENTINEL] No GEMINI_API_KEY — rule-based only.", file=sys.stderr)
        elif openai_key and openai_key.strip():
            self.llm = ChatOpenAI(model=model, temperature=0.3, streaming=True)
            print(f"[SENTINEL] OpenAI provider: {model}", file=sys.stderr)
        else:
            self.llm = None
            print("[SENTINEL] No API keys — rule-based only.", file=sys.stderr)

    async def run_mission_loop(self) -> None:
        print("Starting SENTINEL Commander-Pilot Agent...", file=sys.stderr)
        server_params = StdioServerParameters(command="python", args=[self.server_script_path])

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                print("MCP connected — Commander-Pilot mode.", file=sys.stderr)

                async with aiohttp.ClientSession() as http_session:
                    # Shared Blackboard
                    board = Blackboard(
                        priority_map={},
                        posture="SPREAD",
                        urgent_redirect=None,
                        updated_at_tick=0,
                        tick=0,
                        zone_claims={},
                        lock=asyncio.Lock(),
                    )

                    # Asyncio event primitives
                    commander_trigger: asyncio.Queue = asyncio.Queue()
                    idle_events: dict[str, asyncio.Event] = {
                        f"ALPHA-{i}": asyncio.Event() for i in range(1, 6)
                    }

                    # Spawn Commander + 5 Pilot background tasks
                    commander = Commander(board, self.memory, self.llm, http_session, self.backend_url)
                    pilots = {
                        did: Pilot(did, board, self.memory, self.llm, mcp_session, http_session, self.backend_url)
                        for did in idle_events
                    }
                    bg_tasks = [
                        asyncio.create_task(commander.run(commander_trigger), name="commander"),
                        *[
                            asyncio.create_task(pilots[did].run(idle_events[did]), name=f"pilot-{did}")
                            for did in idle_events
                        ],
                    ]

                    try:
                        await self._poll_loop(mcp_session, http_session, board, commander_trigger, idle_events)
                    finally:
                        for t in bg_tasks:
                            t.cancel()
                        await asyncio.gather(*bg_tasks, return_exceptions=True)

    async def _poll_loop(
        self,
        mcp_session,
        http_session: aiohttp.ClientSession,
        board: Blackboard,
        commander_trigger: asyncio.Queue,
        idle_events: dict[str, asyncio.Event],
    ) -> None:
        import re
        tick = 0
        mission_active = False
        mission_complete_logged = False
        last_victim_ids: set = set()
        last_lead_ids: set = set()
        last_commander_tick = 0

        while True:
            tick += 1
            board.tick = tick

            # Scrub expired zone claims
            async with board.lock:
                board.zone_claims = {
                    z: c for z, c in board.zone_claims.items()
                    if c.expires_at_tick > tick
                }

            # Poll idle drones
            try:
                poll_result = await mcp_session.call_tool("get_idle_drones", {})
                poll_text = poll_result.content[0].text if poll_result.content else "NO_IDLE_DRONES"
            except Exception as e:
                print(f"[POLL] Error: {e}", file=sys.stderr)
                await asyncio.sleep(0.5)
                continue

            # Mission complete
            if "MISSION COMPLETE" in poll_text:
                if not mission_complete_logged:
                    mission_complete_logged = True
                    mission_active = False
                    self.session_log.close()
                    try:
                        await http_session.post(
                            f"{self.backend_url}/log",
                            params={"text": "🏁 MISSION COMPLETE — SENTINEL standing down.", "level": "AI"}
                        )
                    except Exception:
                        pass
                await asyncio.sleep(2.0)
                continue

            # Mission start
            if "MISSION START" in poll_text and not mission_active:
                mission_active = True
                mission_complete_logged = False
                self.memory.reset()
                self.contracts.reset()
                self.session_log.start()
                historical_intel = self.session_log.load_insights()
                await commander_trigger.put({
                    "event": "mission_start",
                    "tick": tick,
                    "payload": {},
                    "historical_intel": historical_intel,
                })
                last_victim_ids = set()
                last_lead_ids = set()
                last_commander_tick = tick

            # Fire idle events for each idle drone
            if "NO_IDLE_DRONES" not in poll_text and "NO_ZONES_AVAILABLE" not in poll_text:
                for m in re.finditer(r'\[DRONE:\s*(\S+)\]', poll_text):
                    drone_id = m.group(1)
                    if drone_id in idle_events and not idle_events[drone_id].is_set():
                        idle_events[drone_id].set()

            # Fetch full state for event detection and contract checks
            try:
                resp = await http_session.get(f"{self.backend_url}/state")
                state = await resp.json()
            except Exception:
                state = {}

            if state.get("stats", {}).get("mission_active", False):
                # Contract checks → fire Commander
                alerts = self.contracts.check(state, tick)
                for alert in alerts:
                    await commander_trigger.put({"event": f"contract", "tick": tick, "payload": {"alert": alert}})

                # Survivor found?
                current_victim_ids = {v.get("id") for v in state.get("victims", [])}
                if current_victim_ids - last_victim_ids:
                    await commander_trigger.put({"event": "survivor_found", "tick": tick, "payload": {}})
                last_victim_ids = current_victim_ids

                # New grounded lead?
                current_lead_ids = {
                    l.get("id") for l in state.get("leads", [])
                    if l.get("status") in ("GROUNDED", "PENDING_GROUND")
                }
                if current_lead_ids - last_lead_ids:
                    await commander_trigger.put({"event": "lead_grounded", "tick": tick, "payload": {}})
                last_lead_ids = current_lead_ids

                # Battery crisis?
                drones_active = [d for d in state.get("drones", []) if d.get("is_active", True)]
                if drones_active:
                    avg_bat = sum(d.get("battery", 100) for d in drones_active) / len(drones_active)
                    if avg_bat < 40:
                        await commander_trigger.put({"event": "battery_crisis", "tick": tick, "payload": {"avg_battery": round(avg_bat, 1)}})

                # Periodic Commander trigger every 60 ticks (30 s at 0.5 s poll)
                if tick - last_commander_tick >= 60:
                    last_commander_tick = tick
                    await commander_trigger.put({"event": "timer", "tick": tick, "payload": {}})

            # Log tick to JSONL
            try:
                self.session_log.log_tick(
                    tick=tick, state=state,
                    events=list(self.memory.tier0[-3:]),
                    decision_type="commander-pilot",
                    assignments=[],
                    contract_alerts=alerts if "alerts" in dir() else [],
                )
            except Exception:
                pass

            await asyncio.sleep(0.5)
```

- [ ] **Step 2: Verify the `__main__` block at the bottom of `agent/agent.py` is unchanged**

It should still read:
```python
if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if len(sys.argv) < 2:
        print("Usage: python agent.py <path_to_server_script.py>", file=sys.stderr)
        sys.exit(1)
    orchestrator = AgentOrchestrator(sys.argv[1])
    asyncio.run(orchestrator.run_mission_loop())
```

- [ ] **Step 3: Run all agent tests**

```bash
python -m pytest agent/tests/ -v
```

Expected: all tests pass. The Orchestrator refactor doesn't break existing unit tests because those test individual classes.

- [ ] **Step 4: Syntax check**

```bash
python -c "import sys; sys.path.insert(0,'C:/Users/shaoxian04/Documents/VHack Project'); from agent.agent import AgentOrchestrator; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add agent/agent.py
git commit -m "feat: refactor AgentOrchestrator to thin poller — Commander-Pilot tasks handle all reasoning"
```

---

## Task 7: Remove old dead code from agent.py

**Files:**
- Modify: `agent/agent.py` — delete old constants and helpers no longer needed

After Task 6, the following are now dead code:

- `SYSTEM_PROMPT` constant (replaced by `COMMANDER_SYSTEM_PROMPT` and `PILOT_SYSTEM_PROMPT`)
- `TokenStreamHandler` class (streaming now handled per-Pilot via `_broadcast`)
- `_execute_rule_based` method stub at bottom of file

- [ ] **Step 1: Delete `SYSTEM_PROMPT` constant**

Find and delete the large `SYSTEM_PROMPT = """..."""` block (lines ~37–128 in the original file).

- [ ] **Step 2: Delete `TokenStreamHandler` class**

Find and delete the `class TokenStreamHandler(AsyncCallbackHandler):` block.

- [ ] **Step 3: Delete `_execute_rule_based` method**

Find and delete the `async def _execute_rule_based(...)` method at the bottom of the file.

- [ ] **Step 4: Remove unused imports**

Remove these imports that are no longer needed:
```python
from langchain_core.callbacks import AsyncCallbackHandler
```

- [ ] **Step 5: Syntax check**

```bash
python -c "import sys; sys.path.insert(0,'C:/Users/shaoxian04/Documents/VHack Project'); from agent.agent import AgentOrchestrator, Commander, Pilot, Blackboard, ZoneClaim; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Run all tests**

```bash
python -m pytest agent/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add agent/agent.py
git commit -m "chore: remove dead code — old SYSTEM_PROMPT, TokenStreamHandler, _execute_rule_based"
```

---

## Task 8: Integration smoke test

No code changes — this task verifies the system works end-to-end.

- [ ] **Step 1: Start the backend**

```bash
cd "C:/Users/shaoxian04/Documents/VHack Project"
python backend/server.py
```

Expected: FastAPI starts on port 8000, no errors.

- [ ] **Step 2: Start the agent in a second terminal**

```bash
cd "C:/Users/shaoxian04/Documents/VHack Project"
python agent/agent.py backend/server.py
```

Expected: `[SENTINEL] OpenAI provider: gpt-4o-mini` then `MCP connected — Commander-Pilot mode.`

- [ ] **Step 3: Open the frontend and deploy the swarm**

Open `http://localhost:5173`. Click "Deploy Swarm".

- [ ] **Step 4: Observe in the Reasoning Timeline tab**

Verify all of the following within 30 seconds:
- `[COMMANDER BRIEF | tick=1 | mission_start]` appears — Commander ran its first brief
- `[PILOT-ALPHA-1] Reasoning:` entries appear — each Pilot posting its individual decision
- Multiple `[PILOT-ALPHA-N]` entries appear within 3 seconds of each other — parallel reasoning confirmed
- `✓ Assigned Zn` messages show city zones (Z0, Z3, etc.) assigned before flat zones
- No drone shows as idle for more than 2 seconds after another drone finishes a zone

- [ ] **Step 5: Verify city zone priority**

After 60 seconds of mission run, check the Map view. City terrain cells (dark tiles) should be predominantly scanned before flat cells of similar coverage.

- [ ] **Step 6: Commit mission report (no code changes)**

```bash
git add mission_reports/
git commit -m "test: add integration smoke test mission report" 2>/dev/null || echo "No new mission reports to commit"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Think-lock eliminated — Pilots run as independent asyncio tasks (Task 6)
- ✅ City zones prioritised — Commander sets priority_map, `_row_gaps` contract removed (Tasks 2, 4)
- ✅ Judge-visible reasoning — Commander BRIEF + per-Pilot reasoning posted to frontend (Tasks 4, 5)
- ✅ Atomic zone claims — `_commit_zone` with asyncio.Lock, reason-first no PENDING (Task 5)
- ✅ Self-evolution preserved — `load_insights()` passed in `mission_start` event to Commander (Task 6)
- ✅ Helper modules — hooks/memory/session_log/fallback ownership updated (Tasks 5, 6)
- ✅ Model switch — gpt-4o-mini set in env and defaults (Task 1)
- ✅ Error handling — per-Pilot LLM fallback to WeightedPlanner; Commander keeps stale blackboard on failure (Tasks 4, 5)
- ✅ Blackboard expiry scrub — Orchestrator scrubs each poll cycle (Task 6)
- ✅ DECISION regex fixed — `[→>=:\-]?` optional separator in `_parse_llm_decision` (Task 5)

"""
SENTINEL Agent Orchestrator — Commander-Pilot Multi-Agent Architecture.

Architecture:
  - AgentOrchestrator: Thin poller. Fires events to Commander and Pilot tasks.
  - Commander: Strategic LLM agent. Updates shared Blackboard (priority map + posture).
  - Pilot: Tactical LLM agent (one per drone). Wakes on idle, reads Blackboard, commits zone claims.
  - Blackboard: Shared state for coordination.
"""
import os
import sys
import asyncio
import aiohttp
import re
import json
from typing import Optional
from dataclasses import dataclass, field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

# Allow running as `python agent/agent.py` from project root
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agent.memory import MissionMemory
from agent.contracts import ContractChecker
from agent.fallback import WeightedPlanner
from agent.session_log import SessionLog
from agent.hooks import ToolHooks

load_dotenv()

# ─── Data Structures ───────────────────────────────────────────────────────────

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
    brain_mode: str = "AUTO"  # AUTO | CLOUD | EDGE | RULES — operator setting


# ─── Commander Agent ───────────────────────────────────────────────────────────

COMMANDER_SYSTEM_PROMPT = """You are SENTINEL Commander — strategic brain of the 5-drone rescue swarm.

Your job: assess the full fleet state and set priorities that all Pilot agents will follow.

Output EXACTLY this format (all four lines required):
POSTURE: <SPREAD|CONVERGE|LEAD_CHASE|RTB_CAUTIOUS>
PRIORITY: <Z0=X.X, Z1=X.X, Z2=X.X, ...>  (list every zone; hazard-bearing zones get 9-10, city zones 7-9, forest 4-6, flat 1-3)
REDIRECT: (<x>, <y>): <reason>  (omit this line entirely if no urgent redirect)
BRIEF: <1-2 sentences on current mission state and what Pilots should focus on>

Rules:
- Hazard cells (damaged urban zones within city) ALWAYS get the highest weight — they have 7× survivor probability of flat terrain
- City terrain zones ALWAYS get higher weight than flat zones regardless of distance
- LEAD_CHASE posture when a GROUNDED CRITICAL lead exists
- CONVERGE when coverage > 50% — focus on highest remaining scores
- RTB_CAUTIOUS when fleet avg battery < 40%
- SPREAD at mission start — distribute across grid
- Never include "spread across rows" logic — zone score is the only priority signal
"""

class Commander:
    def __init__(self, blackboard: Blackboard, memory: MissionMemory, llm, http_session, backend_url: str):
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
            async with self.http_session.get(f"{self.backend_url}/state") as resp:
                state = await resp.json()
        except Exception as e:
            print(f"[COMMANDER] State fetch failed: {e}", file=sys.stderr)
            return  # keep existing blackboard — stale but valid

        mode = self.blackboard.brain_mode
        if mode == "RULES":
            # Rules mode: derive priorities directly from terrain_counts in
            # /state instead of calling the LLM. Same weights as TERRAIN_SCAN_WEIGHT.
            self._apply_rules_brief(state, tick)
            await self._set_active("RULES")
            await self._broadcast(
                f"[COMMANDER BRIEF | tick={tick} | {event_type}] Posture={self.blackboard.posture} [RULES]"
            )
            return

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
            self._apply_rules_brief(state, tick)
            await self._set_active("RULES")
            return

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=COMMANDER_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            print(f"[COMMANDER] LLM failed: {e}", file=sys.stderr)
            self._apply_rules_brief(state, tick)
            await self._set_active("RULES")
            return

        await self._set_active("CLOUD" if mode != "EDGE" else "EDGE")
        priority_map, posture, urgent_redirect = self._parse_brief(text)
        if priority_map:
            self.blackboard.priority_map = priority_map
        self.blackboard.posture = posture
        self.blackboard.urgent_redirect = urgent_redirect
        self.blackboard.updated_at_tick = tick

        await self._broadcast(f"[COMMANDER BRIEF | tick={tick} | {event_type}] Posture={posture}\n{text}")
        await self._emit_timeline(tick, event_type, posture, len(priority_map))

    def _parse_brief(self, text: str) -> tuple[dict, str, Optional[tuple]]:
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

    async def _set_active(self, name: str) -> None:
        """Notify backend which brain actually produced the last decision."""
        try:
            await self.http_session.post(
                f"{self.backend_url}/brain/active", params={"name": name}
            )
        except Exception:
            pass

    def _apply_rules_brief(self, state: dict, tick: int) -> None:
        """Deterministic Commander brief when LLM is disabled (RULES mode or fallback).

        Uses the enriched terrain_counts on each zone to build a priority_map
        that matches the intent of the LLM prompt: hazard 10, city 8, forest 5,
        flat 2. Posture follows battery + lead state.
        """
        weights = {"hazard": 10.0, "city": 8.0, "forest": 5.0, "flat": 2.0, "lake": 0.0}
        zones = state.get("zone", {}).get("zones", {})
        priority_map: dict[str, float] = {}
        for zid, z in zones.items():
            status = str(z.get("status", "")).upper()
            if "COMPLETE" in status:
                priority_map[zid] = 0.0
                continue
            counts = z.get("terrain_counts", {}) or {}
            if not counts:
                priority_map[zid] = round(float(z.get("score", 1.0)) * 10.0, 2)
                continue
            total = sum(counts.values()) or 1
            weighted = sum(weights.get(k, 1.0) * v for k, v in counts.items()) / total
            priority_map[zid] = round(weighted, 2)

        drones_active = [d for d in state.get("drones", []) if d.get("is_active", True)]
        avg_bat = (
            sum(d.get("battery", 100) for d in drones_active) / len(drones_active)
            if drones_active else 100.0
        )
        has_critical_lead = any(
            l.get("status") in ("GROUNDED", "PENDING_GROUND") and l.get("urgency") == "CRITICAL"
            for l in state.get("leads", [])
        )
        if avg_bat < 40:
            posture = "RTB_CAUTIOUS"
        elif has_critical_lead:
            posture = "LEAD_CHASE"
        elif state.get("stats", {}).get("coverage_pct", 0) > 50:
            posture = "CONVERGE"
        else:
            posture = "SPREAD"

        urgent = None
        for l in state.get("leads", []):
            if l.get("status") in ("GROUNDED", "PENDING_GROUND") and l.get("urgency") == "CRITICAL":
                urgent = (int(l.get("x", 0)), int(l.get("y", 0)), "CRITICAL lead [rules mode]")
                break

        self.blackboard.priority_map = priority_map
        self.blackboard.posture = posture
        self.blackboard.urgent_redirect = urgent
        self.blackboard.updated_at_tick = tick

    async def _emit_timeline(self, tick: int, event_type: str, posture: str, zone_count: int) -> None:
        try:
            await self.http_session.post(
                f"{self.backend_url}/timeline",
                params={
                    "tick": tick, "kind": "DECISION", "brain": "CLOUD", "duration_ms": 0,
                    "payload": json.dumps({
                        "type": "COMMANDER_BRIEF", "trigger": event_type,
                        "posture": posture, "zones_updated": zone_count,
                    }),
                }
            )
        except Exception:
            pass


# ─── Pilot Agent ───────────────────────────────────────────────────────────────

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
- Hazard-bearing zones (damaged urban sectors) outrank everything; city zones outrank forest and flat
- Follow the stated posture
- Never pick a zone not listed in Available zones
"""

class Pilot:
    def __init__(self, drone_id: str, blackboard: Blackboard, memory: MissionMemory, llm, mcp_session, http_session, backend_url: str):
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
            async with self.http_session.get(f"{self.backend_url}/state") as resp:
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
        redirect = None
        async with self.blackboard.lock:
            if self.blackboard.urgent_redirect:
                drone_data = next((d for d in state.get("drones", []) if d["id"] == self.drone_id), {})
                x_r, y_r, reason_r = self.blackboard.urgent_redirect
                dist = abs(drone_data.get("x", 0) - x_r) + abs(drone_data.get("y", 0) - y_r)
                if dist <= 8 and self.hooks.pre_investigate_lead(self.drone_id, x_r, y_r, state):
                    redirect = self.blackboard.urgent_redirect
                    self.blackboard.urgent_redirect = None

        if redirect:
            x, y, reason = redirect
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

        # LLM reasoning or rule-based fallback — gated on operator brain_mode
        mode = self.blackboard.brain_mode
        use_llm = (self.llm is not None) and (mode != "RULES")
        if use_llm:
            prompt = (
                f"Drone: {self.drone_id} | Battery: {battery:.0f}% | "
                f"Posture: {self.blackboard.posture}\n"
                f"Available zones (by priority):\n{available}"
            )
            try:
                response = await self.llm.ainvoke([
                    SystemMessage(content=PILOT_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])
                text = response.content if hasattr(response, "content") else str(response)
                primary, backup = self._parse_llm_decision(text)
                await self._broadcast(
                    f"[PILOT-{self.drone_id}] Reasoning:\n{text}"
                )
                await self._set_active("CLOUD" if mode != "EDGE" else "EDGE")
            except Exception as e:
                print(f"[PILOT-{self.drone_id}] LLM failed, using fallback: {e}", file=sys.stderr)
                primary, backup = self._fallback_decision(poll_text, taken)
                await self._set_active("RULES")
        else:
            primary, backup = self._fallback_decision(poll_text, taken)
            await self._broadcast(
                f"[SMART-FALLBACK] {self.drone_id} rule-based (mode={mode}): "
                f"primary={primary}"
            )
            await self._set_active("RULES")

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

    async def _commit_zone(self, primary: str, backup: Optional[str]) -> Optional[str]:
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

    def _parse_llm_decision(self, text: str) -> tuple[Optional[str], Optional[str]]:
        primary = backup = None
        # Optional separator: → >= :- or just space
        m = re.search(r'DECISION\s*[→>=:\-]?\s+(\w+)', text, re.IGNORECASE)
        if m:
            primary = m.group(1).upper()
        m = re.search(r'BACKUP\s*[→>=:\-]?\s+(\w+)', text, re.IGNORECASE)
        if m:
            backup = m.group(1).upper()
        return primary, backup

    def _fallback_decision(self, poll_text: str, taken: set) -> tuple[Optional[str], Optional[str]]:
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
        lines.sort(reverse=True, key=lambda x: x[0])
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

    async def _set_active(self, name: str) -> None:
        try:
            await self.http_session.post(
                f"{self.backend_url}/brain/active", params={"name": name}
            )
        except Exception:
            pass


# ─── Agent Orchestrator ────────────────────────────────────────────────────────

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
                async with http_session.get(f"{self.backend_url}/state") as resp:
                    state = await resp.json()
            except Exception:
                state = {}

            # Mirror operator-set brain_mode into the Blackboard so Commander
            # and Pilot can gate LLM vs rule-based paths without extra GETs.
            brain = state.get("brain", {})
            new_mode = str(brain.get("mode", "AUTO")).upper()
            if new_mode in ("AUTO", "CLOUD", "EDGE", "RULES"):
                board.brain_mode = new_mode

            if state.get("stats", {}).get("mission_active", False):
                # Contract checks → fire Commander
                alerts = self.contracts.check(state, tick)
                for alert in alerts:
                    await commander_trigger.put({"event": "contract", "tick": tick, "payload": {"alert": alert}})

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
                    contract_alerts=alerts if "alerts" in locals() else [],
                )
            except Exception:
                pass

            await asyncio.sleep(0.5)


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if len(sys.argv) < 2:
        print("Usage: python agent.py <path_to_server_script.py>", file=sys.stderr)
        sys.exit(1)

    orchestrator = AgentOrchestrator(sys.argv[1])
    asyncio.run(orchestrator.run_mission_loop())

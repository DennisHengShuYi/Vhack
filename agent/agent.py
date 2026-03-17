"""
SENTINEL Agent Orchestrator — LangChain + LangGraph + GPT-4o via MCP.

Architecture:
  - Connects to backend/server.py via MCP stdio
  - Discovers tools (list_drones, get_idle_drones, assign_scan_zone, return_to_base, etc.)
  - Two-phase loop:
      PHASE 1 (POLL): Calls get_idle_drones() — no LLM, cheap MCP call
      PHASE 2 (EXECUTE): If idle drones exist, invokes GPT-4o via LangGraph ReAct agent
  - Streams chain-of-thought reasoning to frontend via POST /log
  - Falls back to rule-based planner if LLM is unavailable or times out
"""
import os
import sys
import asyncio
import aiohttp
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

load_dotenv()

# ─── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are SENTINEL — the Strategic AI Commander of a 5-drone autonomous rescue swarm.

=== OPERATIONAL ZONE ===
Disaster grid: 20×15. Twelve search sectors (4 columns × 3 rows, each 5×5 cells):

  ROW 0 (y 0–4):   Z0 (NW), Z1 (N), Z2 (NE), Z3 (NE2)
  ROW 1 (y 5–9):   Z4 (W),  Z5 (C), Z6 (CE), Z7 (E)
  ROW 2 (y 10–14): Z8 (SW), Z9 (S), Z10 (SE), Z11 (SE2)

Zone priorities are computed dynamically from terrain — HIGH means many city cells detected.

=== TERRAIN TYPES ===
- CITY cells: Dense population — highest survivor probability. Zones with City terrain are HIGH priority.
- FOREST cells: Hikers/campers — moderate survivor probability. Slightly higher battery cost to traverse.
- FLAT cells: Open ground — low baseline probability.
- LAKE cells: Water — no survivors, impassable (drones route around them).
The Terrain=[...] field in each option shows cell counts per type — use this to prioritise zones with more City cells when distances are similar.

=== YOUR MANDATE ===
For EVERY idle drone, output EXACTLY this analysis block BEFORE any tool calls:

  DRONE [id] @ (x,y) | Battery: B%
    TRADEOFF: [1 sentence comparing the top 2 options — proximity vs priority]
    DECISION → [zone_id]: [reason in ≤15 words]

Then execute ALL assignments in one batch of tool calls.
Never call assign_scan_zone() before writing the analysis block for that drone.
If "Battery too low" → write DECISION → RTB: battery insufficient, then call return_to_base().

After all analysis blocks, write one mission-level note:
  MISSION PULSE: [1 sentence on coverage pace or any zone needing urgent attention]

=== STRATEGIC RULES ===
- Never leave an idle drone without an assignment.
- Assign drones to DIFFERENT zones whenever possible (avoid overlap).
- Never assign a zone already listed as IN_PROGRESS — another drone is scanning it.
- Opt 1 (nearest) is usually best unless Opt 2/3 is HIGH priority AND transit difference is ≤ 5 cells.
- Prefer [PARTIAL-resume] zones — they have saved scan progress and will complete faster.
- ALPHA-5 assists the most-needed zone or covers zones another drone abandoned.
- If all zones are claimed or no valid option, send idle drones to return_to_base().

Write your Mission Log clearly so the human observer can follow your logic, then execute all assignments.

=== MISSION START PROTOCOL ===
When you see "MISSION START — STRATEGIC BRIEFING REQUIRED":
1. Review the terrain analysis already logged (shows zone priorities from city/forest/lake counts).
2. Write a concise Mission Plan BEFORE calling any tools:
   - List which HIGH-priority zones you will target first and which drones you'll send.
   - Note any LOW-priority zones you'll assign only after high-value zones are covered.
3. Then execute all assignments in one pass.
This briefing runs only once at mission start. Subsequent rounds follow the normal mandate.
"""


# ─── Token Streaming ───────────────────────────────────────────────────────────
from langchain_core.callbacks import AsyncCallbackHandler

class TokenStreamHandler(AsyncCallbackHandler):
    """Buffers LLM tokens and posts the complete reasoning block when generation finishes."""
    def __init__(self, broadcast_fn, http_session):
        self.broadcast_fn = broadcast_fn
        self.http_session = http_session
        self._buffer: list[str] = []

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        if token:
            self._buffer.append(token)

    async def on_llm_end(self, response, **kwargs) -> None:
        if self._buffer:
            full_text = "".join(self._buffer).strip()
            self._buffer = []
            if full_text:
                await self.broadcast_fn(self.http_session, full_text)


# ─── Agent Orchestrator ────────────────────────────────────────────────────────
class AgentOrchestrator:
    def __init__(self, server_script_path: str):
        self.server_script_path = server_script_path
        self.backend_url = "http://127.0.0.1:8000"
        self.mission_memory: list[str] = []  # Rolling log of key mission events

        openai_key = os.getenv("OPENAI_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        provider = os.getenv("ACTIVE_PROVIDER", "").upper()
        model = os.getenv("LLM_MODEL", "")

        if provider == "GEMINI" or (not provider and gemini_key and (not openai_key or not openai_key.strip())):
            if gemini_key:
                # Use Gemini via OpenAI-compatible endpoint
                self.llm = ChatOpenAI(
                    model=model or "gemini-2.5-flash",
                    openai_api_key=gemini_key,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    temperature=0,
                    streaming=True
                )
                self.llm_active = True
                print(f"[SENTINEL] Using Gemini provider with model: {model or 'gemini-2.5-flash'}", file=sys.stderr)
            else:
                self.llm = None
                self.llm_active = False
                print("[SENTINEL] No GEMINI_API_KEY — rule-based fallback only.", file=sys.stderr)
        elif openai_key and openai_key.strip():
            self.llm = ChatOpenAI(model=model or "gpt-4o", temperature=0, streaming=True)
            self.llm_active = True
            print(f"[SENTINEL] Using OpenAI provider with model: {model or 'gpt-4o'}", file=sys.stderr)
        else:
            self.llm = None
            self.llm_active = False
            print("[SENTINEL] No API keys — rule-based fallback only.", file=sys.stderr)

    async def _broadcast_log(self, session: aiohttp.ClientSession, msg: str):
        """Posts a log entry to the backend, which adds it to the mission log."""
        try:
            await session.post(f"{self.backend_url}/log", params={"text": msg, "level": "AI"})
        except Exception as e:
            print(f"Failed to broadcast log: {e}", file=sys.stderr)

    def _rule_based_assignments(self, poll_text: str) -> list[tuple[str, str, Optional[str]]]:
        """
        Fallback: parse the options menu and greedily assign each drone to its
        highest-scored valid option (Opt 1), or return_to_base if none available.
        Returns a list of (tool_name, drone_id, zone_id_or_none) tuples.
        """
        actions = []
        current_drone = None
        for line in poll_text.splitlines():
            line = line.strip()
            if line.startswith("[DRONE:"):
                # Extract drone ID: "[DRONE: ALPHA-1] Battery: 100.0% @ (5,12)"
                current_drone = line.split("DRONE:")[1].split("]")[0].strip()
            elif line.startswith("Opt 1:") and current_drone:
                # Extract zone: assign_scan_zone("ALPHA-1", "Z0")
                if "assign_scan_zone" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        actions.append(("assign", current_drone, parts[3]))
                        current_drone = None
            elif "return_to_base()" in line and current_drone:
                actions.append(("return", current_drone, None))
                current_drone = None
        return actions

    def _extract_memory_events(self, messages: list, tick: int) -> list[str]:
        """Parses tool results after each tick and extracts key mission events."""
        events = []
        for m in messages:
            if m.type == "tool":
                content = str(m.content)
                if "survivor" in content.lower() and ("found" in content.lower() or "detected" in content.lower()):
                    events.append(f"Tick {tick}: Survivor detected — {content[:80]}")
                if "complete" in content.lower() and "zone" in content.lower():
                    events.append(f"Tick {tick}: Zone completed — {content[:60]}")
                if "low battery" in content.lower() or "rtb" in content.lower():
                    events.append(f"Tick {tick}: Battery RTB triggered — {content[:60]}")
        return events

    def _is_trivial(self, poll_text: str) -> bool:
        """Returns True if every idle drone has exactly 1 valid option or must RTB — no tradeoff."""
        drones_mentioned = poll_text.count("[DRONE:")
        opt1_count = poll_text.count("Opt 1:")
        rtb_count = poll_text.count("Battery too low for any zone")
        return (opt1_count + rtb_count) == drones_mentioned and "Opt 2:" not in poll_text

    async def run_mission_loop(self):
        """Connects to the MCP server and runs the autonomous mission loop."""
        print("Starting SENTINEL Agent Orchestrator...", file=sys.stderr)

        server_params = StdioServerParameters(
            command="python",
            args=[self.server_script_path]
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Connected to MCP Drone Server.", file=sys.stderr)

                tools = await load_mcp_tools(session)
                print(f"Discovered Tools: {[t.name for t in tools]}", file=sys.stderr)

                agent_executor = None
                if self.llm_active:
                    token_handler_ref = None
                    agent_executor = create_react_agent(self.llm, tools)

                async with aiohttp.ClientSession() as http_session:
                    token_handler = TokenStreamHandler(self._broadcast_log, http_session)
                    tick = 0

                    while True:
                        tick += 1

                        # ── PHASE 1: POLL (no LLM) ──────────────────────────
                        try:
                            poll_result = await session.call_tool("get_idle_drones", {})
                            poll_text = poll_result.content[0].text if poll_result.content else "NO_IDLE_DRONES"
                        except Exception as e:
                            print(f"[POLL] Error: {e}", file=sys.stderr)
                            await asyncio.sleep(1.0)
                            continue

                        if "NO_IDLE_DRONES" in poll_text:
                            await asyncio.sleep(0.5)
                            continue

                        print(f"\n--- SENTINEL Tick {tick} ---", file=sys.stderr)

                        if "MISSION COMPLETE" in poll_text:
                            await self._broadcast_log(http_session, f"[SENTINEL] {poll_text}")
                            print(f"[SENTINEL] {poll_text}", file=sys.stderr)
                            await asyncio.sleep(5.0)
                            continue

                        # Reset memory on mission start
                        if "MISSION START" in poll_text:
                            self.mission_memory = []

                        # ── PHASE 2: EXECUTE (LLM or rule-based) ────────────
                        is_trivial = self._is_trivial(poll_text)

                        if self.llm_active and agent_executor is not None and not is_trivial:
                            # Build memory block for injection
                            memory_block = ""
                            if self.mission_memory:
                                memory_block = "\n\n=== MISSION MEMORY (recent key events) ===\n"
                                memory_block += "\n".join(f"  • {e}" for e in self.mission_memory[-8:])
                                memory_block += "\n=== END MEMORY ===\n"

                            messages = [
                                SystemMessage(content=SYSTEM_PROMPT),
                                HumanMessage(content=f"{memory_block}Execute assignments for these idle drones:\n\n{poll_text}")
                            ]
                            try:
                                async for state in agent_executor.astream(
                                    {"messages": messages},
                                    config={"callbacks": [token_handler]},
                                    stream_mode="values"
                                ):
                                    messages = state["messages"]
                                    latest_msg = messages[-1]
                                    if latest_msg.type == "ai" and getattr(latest_msg, 'tool_calls', None):
                                        for tc in latest_msg.tool_calls:
                                            print(f"  [CMD] {tc['name']}({tc['args']})", file=sys.stderr)
                                    elif latest_msg.type == "tool":
                                        print(f"  [RES] {latest_msg.content[:80]}", file=sys.stderr)
                                        await self._broadcast_log(http_session, f"[SYSTEM] {latest_msg.content}")

                                # Extract and store memory events from this tick
                                new_events = self._extract_memory_events(messages, tick)
                                self.mission_memory.extend(new_events)

                            except asyncio.TimeoutError:
                                await self._broadcast_log(http_session, "⏱️ LLM timeout — rule-based fallback.")
                                await self._execute_rule_based(session, poll_text)
                            except Exception as e:
                                print(f"  [ERROR] {e}", file=sys.stderr)
                                await self._broadcast_log(http_session, f"[ERROR] {e}")
                        else:
                            # Rule-based fallback — no LLM, or trivial tick
                            actions = self._rule_based_assignments(poll_text)
                            if is_trivial and self.llm_active:
                                await self._broadcast_log(http_session,
                                    "[AUTO] No tradeoff — single valid option per drone, rule-based assignment used")
                            for action in actions:
                                try:
                                    if action[0] == "assign":
                                        result = await session.call_tool(
                                            "assign_scan_zone",
                                            {"drone_id": action[1], "zone_id": action[2]}
                                        )
                                        msg = result.content[0].text if result.content else "done"
                                        await self._broadcast_log(http_session, f"[ROUTING] {msg}")
                                    elif action[0] == "return":
                                        result = await session.call_tool(
                                            "return_to_base",
                                            {"drone_id": action[1]}
                                        )
                                        msg = result.content[0].text if result.content else "done"
                                        await self._broadcast_log(http_session, f"[RTB] {msg}")
                                except Exception as e:
                                    print(f"  [FALLBACK ERROR] {e}", file=sys.stderr)

                        print("-" * 30, file=sys.stderr)
                        await asyncio.sleep(0.5)

    async def _execute_rule_based(self, session, poll_text: str):
        """Execute rule-based assignments directly via MCP."""
        actions = self._rule_based_assignments(poll_text)
        for action in actions:
            try:
                if action[0] == "assign":
                    await session.call_tool("assign_scan_zone",
                                            {"drone_id": action[1], "zone_id": action[2]})
                elif action[0] == "return":
                    await session.call_tool("return_to_base", {"drone_id": action[1]})
            except Exception as e:
                print(f"  [FALLBACK ERROR] {e}", file=sys.stderr)


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if len(sys.argv) < 2:
        print("Usage: python agent.py <path_to_server_script.py>", file=sys.stderr)
        sys.exit(1)

    orchestrator = AgentOrchestrator(sys.argv[1])
    asyncio.run(orchestrator.run_mission_loop())

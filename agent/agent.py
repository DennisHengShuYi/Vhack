import os
import sys
import json
import asyncio
import aiohttp
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

load_dotenv()

# System prompt — Agent validates and executes server recommendations
SYSTEM_PROMPT = """You are the Strategic Commander of a Search-and-Rescue Drone Fleet.

You will receive a 'Mission Options Menu' for idle drones. Your goal is to coordinate the fleet to find all survivors as efficiently and safely as possible.

### Your Mandate:
1. **Analyze Options**: For each drone, evaluate the provided options. 
2. **Prioritize Strategy**: High-priority zones should be scanned first, but consider the 'Risk' level. A 'HIGH' risk means the drone will return with very little battery.
3. **Reasoning Trace**: Write a **concise but detailed Mission Log** using markdown before calling any tools. 
   - Explain *why* you chose a specific option for a drone (e.g., "Choosing Option 1 for Drone 1 to secure the High Priority zone Z4 despite the Medium risk").
   - If you decide to recall a drone instead of assigning it a zone, explain why (e.g., "Recalling Drone 2 to avoid a mid-mission failure due to low battery").
4. **Execution**: Execute the chosen commands for ALL idle drones in parallel tool calls.

Format your Mission Log clearly so the human observer can follow your logic.
"""

from langchain_core.callbacks import AsyncCallbackHandler

class TokenStreamHandler(AsyncCallbackHandler):
    """Callback handler to stream tokens to the frontend in real-time."""
    def __init__(self, broadcast_fn, http_session):
        self.broadcast_fn = broadcast_fn
        self.http_session = http_session

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        if token:
            await self.broadcast_fn(self.http_session, token, is_stream=True)

class AgentOrchestrator:
    def __init__(self, server_script_path: str):
        self.server_script_path = server_script_path
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0, streaming=True) 
        self.backend_url = "http://127.0.0.1:8000"

    async def _broadcast_log(self, session: aiohttp.ClientSession, msg: str, is_stream: bool = False):
        """Sends a log to the FastAPI backend to be broadcast to the frontend."""
        try:
            payload = {"text": msg}
            if is_stream:
                payload["is_stream"] = True
            await session.post(f"{self.backend_url}/log", json=payload)
        except Exception as e:
            print(f"Failed to broadcast log: {e}", file=sys.stderr)

    async def run_mission_loop(self):
        """Connects to the MCP server and runs the autonomous loop."""
        print("Starting Agent Orchestrator...")
        
        server_params = StdioServerParameters(
            command="python",
            args=[self.server_script_path]
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Connected to MCP Drone Server.")

                tools = await load_mcp_tools(session)
                print(f"Discovered Tools: {[t.name for t in tools]}")
                
                agent_executor = create_react_agent(self.llm, tools)
                
                async with aiohttp.ClientSession() as http_session:
                    token_handler = TokenStreamHandler(self._broadcast_log, http_session)
                    tick = 0
                    
                    while True:
                        tick += 1
                        
                        # =============================================
                        # PHASE 1: POLL (No LLM — cheap MCP call)
                        # =============================================
                        try:
                            poll_result = await session.call_tool("get_idle_drones", {})
                            poll_text = poll_result.content[0].text if poll_result.content else "NO_IDLE_DRONES"
                        except Exception as e:
                            print(f"[POLL] Error: {e}", file=sys.stderr)
                            await asyncio.sleep(1.0)
                            continue
                        
                        # Silence the noise: If no idle drones or just waiting, don't broadcast
                        if "NO_IDLE_DRONES" in poll_text:
                            await asyncio.sleep(1.0)
                            continue
                        
                        # =============================================
                        # PHASE 2: EXECUTE (Fast LLM — just validate & call tools)
                        # =============================================
                        print(f"\n--- Mission Tick {tick} ---")
                        
                        # Only broadcast "Mission Complete" or "Options Menu"
                        if "MISSION COMPLETE" in poll_text:
                            await self._broadcast_log(http_session, f"[SYSTEM] {poll_text}")
                            print(f"[SYSTEM] {poll_text}")
                            await asyncio.sleep(5.0) # Wait longer if finished
                            continue

                        # For active menus, we don't necessarily need to broadcast the raw menu 
                        # because the Agent's reasoning will explain the choices.
                        # But we can log it as a subtle system message.
                        print(f"[MENU] {poll_text[:100]}...")
                        
                        messages = [
                            SystemMessage(content=SYSTEM_PROMPT),
                            HumanMessage(content=f"Execute these recommended assignments now:\n\n{poll_text}")
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
                                        print(f"  [COMMAND] {tc['name']}({tc['args']})")
                                elif latest_msg.type == "tool":
                                    print(f"  [RESULT] {latest_msg.content[:80]}")
                                    await self._broadcast_log(http_session, f"[SYSTEM] {latest_msg.content}")

                        except Exception as e:
                            print(f"  [ERROR] {e}", file=sys.stderr)
                            await self._broadcast_log(http_session, f"Error: {e}")
                            
                        print("-" * 30)
                        await asyncio.sleep(0.5)

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    if len(sys.argv) < 2:
        print("Usage: python agent.py <path_to_server_script.py>")
        sys.exit(1)
        
    orchestrator = AgentOrchestrator(sys.argv[1])
    asyncio.run(orchestrator.run_mission_loop())

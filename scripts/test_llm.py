import os
import asyncio
from dotenv import load_dotenv

# Add backend to sys.path to import llm_gateway
import sys
sys.path.append(os.path.join(os.getcwd(), 'backend'))

import llm_gateway

load_dotenv()

async def test_completion():
    try:
        print("Testing completion...")
        resp = await asyncio.to_thread(
            llm_gateway.completion,
            messages=[{"role": "user", "content": "Hello, this is a test."}]
        )
        print(f"Success: {resp.choices[0].message.content}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_completion())

import os
import asyncio
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

async def test_full_name():
    api_key = os.getenv("GEMINI_API_KEY")
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    
    # Test with prefix
    try:
        print("Testing models/gemini-2.5-flash...")
        resp = client.chat.completions.create(
            model="models/gemini-2.5-flash",
            messages=[{"role": "user", "content": "Hi"}]
        )
        print(f"Success with prefix: {resp.choices[0].message.content[:20]}...")
    except Exception as e:
        print(f"Error with prefix: {e}")

    # Test without prefix
    try:
        print("Testing gemini-2.5-flash...")
        resp = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "Hi"}]
        )
        print(f"Success without prefix: {resp.choices[0].message.content[:20]}...")
    except Exception as e:
        print(f"Error without prefix: {e}")

if __name__ == "__main__":
    asyncio.run(test_full_name())

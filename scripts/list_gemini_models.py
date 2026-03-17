import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
client = OpenAI(
    api_key=api_key,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

try:
    models = client.models.list()
    for m in models.data:
        print(m.id)
except Exception as e:
    print(f"Error listing models: {e}")

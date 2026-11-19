
import os
from google import genai

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing.")

client = genai.Client(api_key=api_key)

print("=== AVAILABLE GEMINI FLASH MODELS ===")

for model in client.models.list():
    name = model.name or ""
    actions = model.supported_actions or []

    if "flash" in name.lower() and "generateContent" in actions:
        print(name)

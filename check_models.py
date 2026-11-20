
import os
from google import genai
from google.genai import types
from gemini_authorization import CATALOG_DISCLOSURE, confirm_cli

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing.")

confirm_cli(CATALOG_DISCLOSURE)
client = genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))

try:
    print("=== GEMINI FLASH MODELS ON THE FIRST PAGE ===")

    for model in client.models.list().page:
        name = model.name or ""
        actions = model.supported_actions or []

        if "flash" in name.lower() and "generateContent" in actions:
            print(name)
finally:
    client.close()

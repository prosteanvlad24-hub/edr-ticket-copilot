
import os
from google import genai
from google.genai import types
from gemini_authorization import CATALOG_DISCLOSURE, confirm_cli
from presentation_safety import failure_text, record_failure

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing.")

try:
    confirm_cli(CATALOG_DISCLOSURE)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        models = client.models.list().page
    finally:
        client.close()
    print("=== GEMINI FLASH MODELS ON THE FIRST PAGE ===")
    for model in models:
        name = model.name or ""
        actions = model.supported_actions or []

        if "flash" in name.lower() and "generateContent" in actions:
            print(name)
except Exception as exc:
    raise SystemExit(failure_text(record_failure(
        "gemini-model-catalog", exc, "The Google Gemini model catalog could not be retrieved.", provider=True,
    ))) from None

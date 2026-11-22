import time
from typing import Type, TypeVar
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import settings
from app.core.budget import calculate_gemini_cost

T = TypeVar("T", bound=BaseModel)
_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

FALLBACK_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]


def call_gemini_structured(
    prompt: str,
    response_schema: Type[T],
    model: str = "gemini-3.8-flash",
) -> tuple[T, float]:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is missing in .env")

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error = None

    for candidate in candidates:
        for attempt in range(2):
            try:
                response = _client.models.generate_content(
                    model=candidate,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=0.2,
                    ),
                )

                usage = response.usage_metadata
                cost_usd = calculate_gemini_cost(
                    model=candidate,
                    input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                )

                parsed = response_schema.model_validate_json(response.text)
                return parsed, cost_usd

            except errors.ServerError as e:
                last_error = e
                if attempt == 0:
                    time.sleep(1)
                    continue
                break  # move to next fallback model
            except errors.ClientError as e:
                last_error = e
                break  # 404/429 -> immediately try next fallback model

    raise last_error
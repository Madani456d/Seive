import asyncio
from typing import Type, TypeVar, Literal
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai.errors import APIError
from app.core.config import settings

T = TypeVar("T", bound=BaseModel)

# Dynamic model tiers for cost-efficiency
MODEL_TIERS = {
    "fast": "gemini-3.8-flash",   # Pre-filtering, simple JSON extraction
    "smart": "gemini-3.8-flash",       # ICP planning, scoring, outreach copy
}


class LLMRouter:
    def __init__(self) -> None:
        self.client = (
            genai.Client(api_key=settings.gemini_api_key)
            if settings.gemini_api_key and settings.gemini_api_key != "your_free_gemini_api_key"
            else None
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        tier: Literal["fast", "smart"] = "fast",
        max_retries: int = 3,
    ) -> T:
        if not self.client:
            raise RuntimeError(
                "GEMINI_API_KEY is missing or still a placeholder in backend/.env"
            )

        model_name = MODEL_TIERS[tier]
        delay = 1.5

        for attempt in range(1, max_retries + 1):
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=0.2,
                    ),
                )
                return response_schema.model_validate_json(response.text)
            except APIError as e:
                if e.code == 429 and attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise


llm_router = LLMRouter()

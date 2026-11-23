from app.core.config import settings

# USD per 1M tokens (update if Google adjusts pricing; note gemini-3.8-flash promo runs through Dec 31, 2026)
GEMINI_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}

DEFAULT_GEMINI_RATES = {"input": 0.75, "output": 3.75}


class BudgetExceededError(Exception):
    pass


def calculate_gemini_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = GEMINI_PRICING_PER_1M.get(model, DEFAULT_GEMINI_RATES)
    safe_in = max(0, int(input_tokens or 0))
    safe_out = max(0, int(output_tokens or 0))
    cost = (safe_in * rates["input"] + safe_out * rates["output"]) / 1_000_000
    return round(cost, 6)


def check_budget(current_spent: float, estimated_next_cost: float = 0.0) -> None:
    spent = max(0.0, float(current_spent or 0.0))
    next_cost = max(0.0, float(estimated_next_cost or 0.0))
    cap = float(getattr(settings, "max_run_budget_usd", 1.0) or 1.0)
    if spent + next_cost > cap:
        raise BudgetExceededError(
            f"Run budget cap (${cap:.4f}) would be exceeded "
            f"(spent: ${spent:.4f}, next: ${next_cost:.4f})."
        )
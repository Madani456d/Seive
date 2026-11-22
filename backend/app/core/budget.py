from app.core.config import settings

# USD per 1M tokens (update if Google adjusts pricing)
GEMINI_PRICING_PER_1M = {
    "gemini-3.8-flash": {"input": 0.10, "output": 0.40},
    "gemini-3.8-flash": {"input": 0.30, "output": 2.50},
}


class BudgetExceededError(Exception):
    pass


def calculate_gemini_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = GEMINI_PRICING_PER_1M.get(model, {"input": 0.30, "output": 2.50})
    cost = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    return round(cost, 6)


def check_budget(current_spent: float, estimated_next_cost: float = 0.0) -> None:
    if current_spent + estimated_next_cost > settings.max_run_budget_usd:
        raise BudgetExceededError(
            f"Run budget cap (${settings.max_run_budget_usd:.4f}) would be exceeded "
            f"(spent: ${current_spent:.4f}, next: ${estimated_next_cost:.4f})."
        )

from __future__ import annotations

import json
import re
from importlib import resources

from .config import Settings
from .errors import ApiError
from .models import BudgetAnalysisRequest, BudgetSummary, ExpenseRecord

PROMPT_ASSET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$")


def build_budget_analysis_prompt(
    settings: Settings,
    summary: BudgetSummary,
    expenses: list[ExpenseRecord],
    request: BudgetAnalysisRequest,
) -> str:
    if PROMPT_ASSET_PATTERN.fullmatch(settings.ai_prompt_asset) is None:
        raise ValueError("STUDENT5_BACKEND_AI_PROMPT_ASSET must name a markdown file.")
    template = (
        resources.files("student5_backend_service")
        .joinpath("prompts", settings.ai_prompt_asset)
        .read_text(encoding="utf-8")
    )
    context = {
        "currency": summary.currency,
        "summary": summary.model_dump(mode="json"),
        "expenses": [expense.model_dump(mode="json") for expense in expenses],
        "question": request.question,
    }
    provider_facts = tuple(
        (
            f"Provider {name}: available, subtotal {provider.currency} "
            f"{provider.subtotal:.2f}, items: {len(provider.items)}"
            if provider.status == "available"
            else f"Provider {name}: {provider.status.value}, detail: {provider.detail}"
        )
        for name, provider in sorted(summary.providers.items())
    )
    key_facts = "\n".join(
        (
            f"Currency: {summary.currency}",
            f"Total budget: {summary.currency} {summary.total_budget:.2f}",
            f"Actual spending: {summary.currency} {summary.actual_spending:.2f} "
            f"(complete: {str(summary.actual_spending_complete).lower()})",
            f"Committed costs: {summary.currency} {summary.committed_costs:.2f} "
            f"(complete: {str(summary.committed_costs_complete).lower()})",
            f"Remaining budget: {summary.currency} {summary.remaining_budget:.2f} "
            f"(complete: {str(summary.remaining_budget_complete).lower()})",
            f"Recorded expenses: {len(expenses)}",
            *provider_facts,
            f"User question: {request.question}",
        )
    )
    prompt = template.replace("{{KEY_FACTS}}", key_facts).replace(
        "{{BUDGET_CONTEXT_JSON}}",
        json.dumps(context, separators=(",", ":"), sort_keys=True),
    )
    if len(prompt) > settings.ai_prompt_max_chars:
        raise ApiError(
            422,
            "PROMPT_BUDGET_EXCEEDED",
            "This budget has too much context for AI analysis.",
            [{"field": "ai_mode", "issue": "rendered prompt exceeds configured limit"}],
        )
    return prompt
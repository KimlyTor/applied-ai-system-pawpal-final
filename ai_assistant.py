"""Claude-powered plan coach for PawPal+.

The rule-based SchedulePlanningAgent still decides the schedule. Claude only
explains the finished plan in plain language and suggests how to fit skipped
tasks, so a bad model answer can never produce an invalid schedule.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from pawpal_system import SchedulePlan, format_window

# Load ANTHROPIC_API_KEY (and optional PAWPAL_CLAUDE_MODEL) from the project's .env.
load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_MODEL = "claude-opus-5-5"

# USD per million tokens (input, output), used only for the on-screen estimate.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

SYSTEM_PROMPT = """You are PawPal+, a friendly pet-care planning coach.
You receive a daily care plan that a rule-based scheduler has already built and
validated. Do not change or re-order the plan; explain it and help the owner.

Return JSON with three fields:
- "why": 2 or 3 sentences on how priority, due times and the owner's free time
  windows (or time budget) shaped the plan. Plain text, no headings.
- "suggestions": exactly one entry per skipped task, in the order listed. Each
  gives one new date (YYYY-MM-DD) and 24-hour time (HH:MM) that would let the
  task be scheduled: on or after the plan date, avoiding the reason it was
  skipped, not overlapping scheduled tasks or your other suggestions, and, if
  free time windows are listed, starting and finishing inside one of them.
  Keep each reason under 20 words. Use an empty list if nothing was skipped.
- "tips": 0 to 2 short, practical care tips for the pets listed. Never mention
  new times or dates in tips; new times belong only in "suggestions".

Use only the tasks, times and pets in the plan. Never invent tasks. Write any
time in "why", reasons, or tips in 12-hour format with AM or PM (e.g. 9:30 AM)."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "why": {"type": "string"},
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "suggested_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "suggested_time": {"type": "string", "description": "24-hour HH:MM"},
                    "reason": {"type": "string"},
                },
                "required": ["suggested_date", "suggested_time", "reason"],
                "additionalProperties": False,
            },
        },
        "tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["why", "suggestions", "tips"],
    "additionalProperties": False,
}


@dataclass
class RescheduleSuggestion:
    suggested_date: date
    suggested_time: time
    reason: str


@dataclass
class CoachReply:
    text: str
    used_ai: bool
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    note: str = ""
    # Aligned by index with plan.skipped_tasks; None where Claude's answer was unusable.
    suggestions: list[Optional[RescheduleSuggestion]] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


def get_api_key() -> Optional[str]:
    """Read the Anthropic key loaded from .env (or the shell environment)."""
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


def get_model() -> str:
    return os.environ.get("PAWPAL_CLAUDE_MODEL", DEFAULT_MODEL)


def _windows_text(plan: SchedulePlan) -> str:
    return ", ".join(format_window(window) for window in plan.free_windows)


def summarize_plan(
    plan: SchedulePlan,
    owner_name: str,
    selected_date: date,
    available_minutes: int,
) -> str:
    """Turn a SchedulePlan into compact text for the prompt."""
    used = sum(task.duration_minutes for _, task in plan.schedule)
    pets = sorted({f"{pet.name} ({pet.species})" for pet, _ in plan.due_today})
    lines = [
        f"Owner: {owner_name}",
        f"Date: {selected_date.isoformat()}",
        f"Pets with tasks today: {', '.join(pets) or 'none'}",
        f"Time budget: {available_minutes} min, used {used} min, "
        f"left {available_minutes - used} min",
        "",
        "Scheduled (in planner order):",
    ]
    if plan.free_windows:
        lines.insert(3, f"Owner's free time windows: {_windows_text(plan)}")
    for pet, task in plan.schedule:
        lines.append(
            f"- {task.due_date.strftime('%H:%M')} {pet.name}: {task.title} "
            f"({task.duration_minutes} min, {task.priority} priority, "
            f"{task.frequency})"
        )
    if not plan.schedule:
        lines.append("- (nothing scheduled)")
    lines.append("")
    lines.append("Skipped:")
    for (pet, task), reason in plan.skipped_tasks:
        lines.append(
            f"- {task.due_date.strftime('%H:%M')} {pet.name}: {task.title} "
            f"({task.duration_minutes} min, {task.priority} priority). "
            f"Reason: {reason}"
        )
    if not plan.skipped_tasks:
        lines.append("- (none)")
    return "\n".join(lines)


def offline_reply(plan: SchedulePlan, note: str) -> CoachReply:
    """Rule-based explanation used when Claude is unavailable."""
    text = (
        f"The planner picked {len(plan.schedule)} of {len(plan.due_today)} "
        "task(s) due today, taking higher-priority tasks first, then earlier "
        "due times, and skipping anything that overlaps or falls outside your time."
    )
    tips = [f"{pet.name}'s {task.title}: {reason}" for (pet, task), reason in plan.skipped_tasks]
    return CoachReply(text=text, used_ai=False, note=note, tips=tips)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICES_PER_MTOK.get(model, PRICES_PER_MTOK[DEFAULT_MODEL])
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def _parse_suggestions(
    raw_items: list, count: int, selected_date: date
) -> list[Optional[RescheduleSuggestion]]:
    suggestions: list[Optional[RescheduleSuggestion]] = []
    for item in raw_items[:count]:
        try:
            new_date = date.fromisoformat(item["suggested_date"])
            hour, minute = item["suggested_time"].split(":")[:2]
            new_time = time(int(hour), int(minute))
        except (KeyError, ValueError, AttributeError, TypeError):
            suggestions.append(None)
            continue
        if new_date < selected_date:
            suggestions.append(None)
            continue
        suggestions.append(RescheduleSuggestion(new_date, new_time, str(item.get("reason", "")).strip()))
    return suggestions + [None] * (count - len(suggestions))


def ask_claude(
    plan: SchedulePlan,
    plan_summary: str,
    selected_date: date,
    api_key: Optional[str],
    client=None,
) -> CoachReply:
    """Ask Claude, in one call, to explain the plan and suggest a new time per skipped task.

    Claude only suggests; the owner decides whether to apply each time, and the
    rule-based scheduler re-checks the plan when they do.
    """
    if client is None:
        if not api_key:
            return offline_reply(
                plan,
                "No ANTHROPIC_API_KEY found in .env, so this is the built-in explanation.",
            )
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=1)

    import anthropic

    count = len(plan.skipped_tasks)
    content = (
        plan_summary
        + f"\n\nReturn exactly {count} suggestions, one per skipped task, in the order listed."
    )
    model = get_model()
    extra = {}
    if "haiku" not in model:
        # If Claude declines, the API retries on a fallback model in the same call.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=2000,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            **extra,
        )
    except anthropic.AuthenticationError:
        return offline_reply(plan, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.RateLimitError:
        return offline_reply(plan, "Claude is rate-limited right now. Try again in a minute.")
    except anthropic.BadRequestError as error:
        return offline_reply(plan, f"Claude rejected the request: {error.message}")
    except anthropic.APIStatusError as error:
        return offline_reply(plan, f"Claude API error ({error.status_code}).")
    except anthropic.APIConnectionError:
        return offline_reply(plan, "Could not reach Claude. Check the internet connection.")

    if response.stop_reason == "refusal":
        return offline_reply(plan, "Claude did not return an answer for this plan.")
    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        data = json.loads(text)
        why = str(data["why"]).strip()
        raw_suggestions = list(data["suggestions"])
        raw_tips = list(data["tips"])
    except (ValueError, KeyError, TypeError):
        return offline_reply(plan, "Claude's answer could not be read, so this is the built-in explanation.")
    if not why:
        return offline_reply(plan, "Claude did not return an answer for this plan.")

    usage = response.usage
    return CoachReply(
        text=why,
        used_ai=True,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=_estimate_cost(model, usage.input_tokens, usage.output_tokens),
        suggestions=_parse_suggestions(raw_suggestions, count, selected_date),
        tips=[str(tip).strip() for tip in raw_tips if str(tip).strip()][:2],
    )

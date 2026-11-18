"""Tests for the Claude plan coach. These use a fake client, so they spend no credit."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from types import SimpleNamespace

from ai_assistant import ask_claude, summarize_plan
from pawpal_system import CareTask, Pet, SchedulePlanningAgent

TODAY = date(2026, 10, 20)


def make_plan():
    walk = CareTask("Walk", "Walk", datetime.combine(TODAY, time(9, 0)), duration_minutes=30, priority="high")
    feed = CareTask("Breakfast", "Breakfast", datetime.combine(TODAY, time(9, 0)), duration_minutes=10)
    mochi = Pet("Mochi", "dog", tasks=[walk])
    luna = Pet("Luna", "cat", tasks=[feed])
    tasks = [(mochi, walk), (luna, feed)]
    return SchedulePlanningAgent().create_plan(tasks, TODAY, 60)


def answer(why="Walk comes first.", suggestions=None, tips=None):
    if suggestions is None:
        suggestions = [{"suggested_date": "2026-10-20", "suggested_time": "09:30", "reason": "After the walk."}]
    return json.dumps({"why": why, "suggestions": suggestions, "tips": tips or []})


class FakeMessages:
    def __init__(self, text=None, stop_reason="end_turn"):
        self.text = answer() if text is None else text
        self.stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=400, output_tokens=150),
        )


def fake_client(**kwargs):
    messages = FakeMessages(**kwargs)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_summary_lists_scheduled_and_skipped_tasks():
    summary = summarize_plan(make_plan(), "Jordan", TODAY, 60)
    assert "09:00 Mochi: Walk" in summary
    assert "Skipped:" in summary and "Luna: Breakfast" in summary
    assert "used 30 min" in summary


def test_one_call_returns_explanation_suggestions_tips_and_cost():
    client, messages = fake_client(text=answer(tips=["Keep water fresh."]))
    reply = ask_claude(make_plan(), "summary", TODAY, api_key=None, client=client)

    assert len(messages.calls) == 1
    assert reply.used_ai
    assert reply.text == "Walk comes first."
    assert reply.suggestions[0].suggested_time == time(9, 30)
    assert reply.tips == ["Keep water fresh."]
    assert reply.estimated_cost_usd > 0
    call = messages.calls[0]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["messages"][0]["content"].startswith("summary")
    assert "Return exactly 1 suggestions" in call["messages"][0]["content"]


def test_suggestions_drop_past_or_malformed_times_and_pad_missing():
    plan = make_plan()
    bad = [{"suggested_date": "2026-10-19", "suggested_time": "09:30", "reason": "x"}]
    client, _ = fake_client(text=answer(suggestions=bad))
    assert ask_claude(plan, "summary", TODAY, api_key=None, client=client).suggestions == [None]

    client, _ = fake_client(text=answer(suggestions=[]))
    assert ask_claude(plan, "summary", TODAY, api_key=None, client=client).suggestions == [None]


def test_missing_key_falls_back_without_calling_api():
    reply = ask_claude(make_plan(), "summary", TODAY, api_key=None)
    assert not reply.used_ai
    assert "ANTHROPIC_API_KEY" in reply.note
    assert any("Breakfast" in tip for tip in reply.tips)
    assert reply.suggestions == []


def test_refusal_or_unreadable_answer_falls_back_to_builtin_explanation():
    client, _ = fake_client(text="", stop_reason="refusal")
    assert not ask_claude(make_plan(), "summary", TODAY, api_key=None, client=client).used_ai

    client, _ = fake_client(text="not json")
    reply = ask_claude(make_plan(), "summary", TODAY, api_key=None, client=client)
    assert not reply.used_ai
    assert "could not be read" in reply.note


def test_summary_includes_free_windows_when_set():
    walk = CareTask("Walk", "Walk", datetime.combine(TODAY, time(7, 0)), duration_minutes=30, priority="high")
    feed = CareTask("Feed", "Feed", datetime.combine(TODAY, time(12, 0)), duration_minutes=10)
    mochi = Pet("Mochi", "dog", tasks=[walk, feed])
    windows = [(time(7, 0), time(9, 0)), (time(17, 0), time(20, 0))]
    plan = SchedulePlanningAgent().create_plan([(mochi, walk), (mochi, feed)], TODAY, free_windows=windows)

    assert "7:00 AM–9:00 AM, 5:00 PM–8:00 PM" in summarize_plan(plan, "Jordan", TODAY, 300)

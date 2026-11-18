# Model Card: PawPal+

## Overview

PawPal+ is a Streamlit app that builds a daily pet-care plan. A **rule-based planning
agent** (`SchedulePlanningAgent` in `pawpal_system.py`) decides the schedule. An optional
**Claude coach** (`ask_claude` in `ai_assistant.py`) explains the finished plan, suggests a
new time for each task that didn't fit, and shares care tips. The owner decides whether to
apply any suggestion.

| | |
|---|---|
| **Model** | Anthropic Claude Opus 5.5 (`claude-opus-5-5`) by default; Claude Haiku 5.5 (`claude-haiku-5-5`) optional via `PAWPAL_CLAUDE_MODEL` |
| **How it's called** | One Messages API call per click of **Get Claude's tips** (or `python main.py --claude`), with low effort and a JSON schema so the answer has a fixed shape |
| **Input sent to Claude** | A short text summary of the plan: owner name, date, pet names and species, the owner's free time windows, scheduled tasks, and skipped tasks with their times, durations, priorities, and why they were skipped |
| **Output** | JSON with three parts: `why` (2–3 sentences explaining the plan), `suggestions` (one new date and time per skipped task, with a short reason), and `tips` (up to two care tips that never mention times) |
| **Cost** | About $0.01 per call with Opus; a fraction of a cent with Haiku |

## Intended use

- Helping one pet owner understand their daily care plan and fit in tasks that were
  skipped because they overlapped another task or fell outside their free time.
- Giving general, everyday care tips (for example, letting a pet rest after a walk).

**Out of scope:** veterinary or medical advice, medication or dosing decisions,
emergencies, and making changes to the schedule without the owner.

## How the AI is kept in check

- **The planner decides, Claude advises.** Claude never edits the schedule. Its suggested
  times only fill in the date and time boxes.
- **The owner approves every change.** Nothing moves until the owner clicks **Apply**, and
  they can change Claude's time first.
- **Every applied change is re-checked.** The rule-based planner rebuilds the plan, so a
  suggested time that overlaps or falls outside free time is shown as "still doesn't fit"
  instead of being scheduled.
- **The answer is validated.** Past dates and malformed times are dropped, and the
  explanation, times, and tips come from one answer so they can't contradict each other.
- **Safe fallbacks.** With no API key, an API error, a refusal, or an unreadable answer,
  the app shows a built-in explanation and says Claude wasn't used. On Opus, a declined
  request is retried on a fallback model in the same call.
- **No stale answers.** If the plan changes after Claude answers, the old answer is hidden.
- **Cost guard.** 5 Claude requests per browser session. The API key lives in `.env`,
  which is git-ignored.

## Evaluation

- **Automated:** 6 tests in `tests/test_ai_assistant.py` use a fake client (no API calls).
  They check the summary sent to Claude, parsing of the explanation, times, and tips,
  dropping bad times, and every fallback path. All pass, along with 19 scheduler tests.
- **By hand:** in 3 live calls on real plans, all 5 suggested times were valid: none
  overlapped a scheduled task, they matched the explanation, and the 4 made with free
  windows all fit inside them. For example, with one 9:00–11:00 AM window and three tasks at 9:00 AM,
  Claude suggested 9:30 AM and 10:30 AM, and applying 9:30 AM put the task into the plan.
- **Not evaluated:** answer quality across many plans, unusual inputs, or other languages.

## Limitations and Biases

**Limitations:**

- **Suggestions can still miss.** Claude can suggest a time that overlaps another task or
  another suggestion. The planner catches this after **Apply**, but the owner has to try
  again.
- **Narrow help.** Claude only suggests new times for skipped tasks. It doesn't reorganize
  the whole day, shorten tasks, or change priorities.
- **Tips aren't checked.** Care tips are general and come straight from Claude. The prompt
  doesn't explicitly forbid health advice, so tips aren't a substitute for a vet.
- **Nothing is saved.** Pets, tasks, and free time live only in the browser session and are
  lost on refresh.
- **One day, fixed times.** Plans cover a single day. Free windows can't cross midnight,
  and the planner never moves a task on its own; only the owner can.
- **Soft cost limit.** The 5-request limit resets when the page is refreshed, so it
  prevents accidental spending, not deliberate overuse.
- **Approximate cost display.** Cost estimates use hard-coded prices for two models.
- **Privacy.** The owner's name, pet names, and task titles are sent to Anthropic's API.
  Owners shouldn't put sensitive personal information in task titles.
- **Needs internet and a key.** Without them, the fallback explanation is generic.
- **English and 12-hour times only.**

**Biases:**

- **Language and format:** English only, and 12-hour US-style times (9:20 AM).
- **Common pets:** Claude's care tips likely fit dogs and cats best; "other" species may
  get generic or less accurate advice.
- **Priority labels decide everything:** a "low" priority task is always dropped first,
  even if it matters more to that pet (like medicine labelled low by mistake).

## Misuse and Prevention

- **Treating tips as medical advice.** An owner might rely on Claude for health decisions.
  Prevention: tips are limited to general care, medical advice is listed as out of scope,
  and Claude can't change medications or tasks on its own. A next step would be telling
  Claude to refer health questions to a vet.
- **Instructions hidden in task titles.** Task titles are sent to Claude, so someone could
  type instructions into a title. Prevention: Claude's answer must match a fixed JSON
  format, its times are checked, and it can only suggest; the planner and owner decide.
- **Running up API costs.** If the app were shared publicly, anyone could use my API key.
  Prevention: the key stays in a git-ignored `.env`, there's a 5-request limit per session,
  and Haiku is available as a cheaper model. For a public app, I'd need real per-user limits.
- **Sharing personal information.** Owner and pet names and task titles are sent to
  Anthropic. Prevention: only the plan summary is sent, and owners shouldn't put sensitive
  details in task titles.

## What Surprised Me While Testing

- **Passing tests didn't mean it worked.** The fake-client tests passed, but the first live
  call failed because the real API rejected part of my request format.
- **Two AI answers disagreed.** When tips and suggested times came from two separate Claude
  calls, they gave different times (9:20 vs 9:30 AM) for the same task.
- **The app looked fine in tests but not in the browser.** The headless test said duplicates
  were crossed out, but the line never actually showed on screen.
- **A "success" message could be wrong.** The green "Plan checked" banner appeared even when
  a task had been left out for being outside free time.

## Reflection

### How I collaborated with AI

I built the Claude features with an AI coding assistant (Claude Code). I described what
I wanted in plain language, for example "let the owner enter several free time windows"
or "the owner should approve a suggested time before it's added". The assistant proposed
an approach, made the code changes, and ran the tests and a headless check of the app.
I then used the app in the browser and reported anything that looked wrong or confusing.
Many fixes started from things I noticed: Claude's tips and suggested times not matching,
the AM/PM box being cut off, and a green "Plan checked" banner showing even though a task
had been skipped. 

### A suggestion I accepted

When I noticed that Claude's tips said "move feeding to 9:20 AM" while the suggested time
said 9:30 AM, the assistant explained that two separate Claude calls were each choosing
their own times. It suggested combining them into **one structured Claude call** that
returns the explanation, one time per skipped task, and the tips together, with tips not
allowed to mention times. I accepted this because it fixed the cause rather than the
symptom, and it also halved the cost. A live test confirmed the times now appear in only
one place and match the explanation.

### A suggestion I rejected or revised

- **Rejected: moving the AM/PM box.**
  - The AM/PM dropdown was cut off to "A…".
  - The assistant's first fix moved the AM/PM box below the time box to give it more room.
  - I rejected that because it broke the layout of the form.
  - I asked for smaller text instead, so AM/PM could stay beside the time.

import argparse
from datetime import date, datetime, time, timedelta

from pawpal_system import (
    CareTask,
    DailyScheduler,
    Owner,
    Pet,
    SchedulePlan,
    SchedulePlanningAgent,
    format_clock_time,
    format_window,
    window_minutes,
)


def clock(value: datetime) -> str:
    return " ".join(format_clock_time(value.time()))


def stamp(value: datetime) -> str:
    return f"{value:%Y-%m-%d} {clock(value)}"


# Needs ANTHROPIC_API_KEY in .env: this is the only part of main.py that calls Claude.
# Without a key, ask_claude returns the built-in explanation instead.
def print_claude_tips(plan: SchedulePlan, owner_name: str, today: date) -> None:
    """Send the plan to Claude (one API call, about a cent) and print its answer."""
    from ai_assistant import ask_claude, get_api_key, get_model, summarize_plan

    total_minutes = sum(window_minutes(window) for window in plan.free_windows)
    summary = summarize_plan(plan, owner_name, today, total_minutes)
    print(f"\nAsking Claude ({get_model()})...")
    reply = ask_claude(plan, summary, today, get_api_key())
    if reply.note:
        print(f"NOTE: {reply.note}")

    print("\nWhy this plan works:")
    print(reply.text)

    if reply.suggestions:
        print("\nSuggested new times:")
        for ((pet, task), _), suggestion in zip(plan.skipped_tasks, reply.suggestions):
            if suggestion is None:
                print(f"- {pet.name}: {task.title}: no usable suggestion")
                continue
            new_due = datetime.combine(suggestion.suggested_date, suggestion.suggested_time)
            print(
                f"- {pet.name}: {task.title} (now {clock(task.due_date)}) -> "
                f"{stamp(new_due)}. {suggestion.reason}"
            )

    if reply.tips:
        print("\nTips:")
        for tip in reply.tips:
            print(f"- {tip}")

    if reply.used_ai:
        print(
            f"\n{reply.input_tokens} input + {reply.output_tokens} output tokens, "
            f"about ${reply.estimated_cost_usd:.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="PawPal+ command-line demo.")
    parser.add_argument(
        "--claude",
        action="store_true",
        help="also ask Claude to explain the plan (one API call, about a cent; needs ANTHROPIC_API_KEY)",
    )
    args = parser.parse_args()

    today = date.today()
    tomorrow = today + timedelta(days=1)
    first_pet = Pet(name="Mochi", species="dog")
    owner = Owner(name="Jordan", pets=[first_pet])
    second_pet = Pet(name="Luna", species="cat")
    owner.add_pet(second_pet)

    first_pet.add_task(
        CareTask(
            description="Tomorrow's breakfast",
            title="Feed",
            due_date=datetime.combine(tomorrow, time(7, 0)),
            duration_minutes=10,
            priority="medium",
            frequency="daily",
        )
    )
    second_pet.add_task(
        CareTask(
            description="Evening playtime",
            title="Play",
            due_date=datetime.combine(today, time(17, 30)),
            duration_minutes=20,
            priority="low",
            frequency="daily",
        )
    )
    completed_task = CareTask(
        description="Morning walk",
        title="Walk",
        due_date=datetime.combine(today, time(8, 0)),
        duration_minutes=30,
        priority="high",
        frequency="daily",
    )
    first_pet.add_task(completed_task)
    completed_task.mark_complete()
    first_pet.add_task(
        CareTask(
            description="Morning walk",
            title="Walk",
            due_date=datetime.combine(today, time(9, 0)),
            duration_minutes=30,
            priority="high",
            frequency="once",
        )
    )
    # The same walk entered twice by mistake: the planner leaves this copy out.
    first_pet.add_task(
        CareTask(
            description="Morning walk",
            title="walk",
            due_date=datetime.combine(today, time(9, 0)),
            duration_minutes=30,
            priority="high",
            frequency="once",
        )
    )
    second_pet.add_task(
        CareTask(
            description="Breakfast",
            title="Breakfast",
            due_date=datetime.combine(today, time(9, 0)),
            duration_minutes=10,
            priority="medium",
            frequency="daily",
        )
    )
    second_pet.add_task(
        CareTask(
            description="Brushing",
            title="Brush",
            due_date=datetime.combine(today, time(12, 0)),
            duration_minutes=15,
            priority="low",
            frequency="daily",
        )
    )

    scheduler = DailyScheduler()
    all_tasks = scheduler.get_tasks(owner)

    # Show tasks in their original order and with their completion status.
    print("Tasks in insertion order:")
    for pet, task in all_tasks:
        status = "completed" if task.is_completed else "incomplete"
        print(f"- {stamp(task.due_date)} {pet.name}: {task.title} ({status})")

    # Demonstrate sorting by full due date and time.
    print("\nTasks sorted by date and time:")
    for pet, task in scheduler.sort_tasks_by_due_date(all_tasks):
        print(f"- {stamp(task.due_date)} {pet.name}: {task.title}")

    # Separate completed tasks from tasks that still need care.
    print("\nCompleted tasks:")
    for pet, task in scheduler.filter_tasks_by_completion_status(
        all_tasks, is_completed=True
    ):
        print(f"- {pet.name}: {task.title}")

    print("\nIncomplete tasks:")
    for pet, task in scheduler.filter_tasks_by_completion_status(
        all_tasks, is_completed=False
    ):
        print(f"- {pet.name}: {task.title}")

    # Catch tasks that were added twice.
    duplicates = scheduler.find_duplicate_tasks(all_tasks)
    print("\nDuplicate tasks:")
    for pet, task in all_tasks:
        if id(task) in duplicates:
            original_pet, original_task = duplicates[id(task)]
            print(
                f"- {pet.name}: {task.title} at {clock(task.due_date)} "
                f"(same as {original_pet.name}'s {original_task.title})"
            )

    # Warn about overlapping times before planning (duplicates excluded).
    unique_tasks = [assignment for assignment in all_tasks if id(assignment[1]) not in duplicates]
    print()
    for (first_pet_, first_task), (second_pet_, second_task) in scheduler.find_time_conflicts(
        unique_tasks, selected_date=today
    ):
        print(
            f"WARNING: Time conflict: {first_pet_.name}'s {first_task.title} overlaps "
            f"{second_pet_.name}'s {second_task.title}."
        )

    # Plan the day inside the owner's free time windows.
    free_windows = [(time(7, 0), time(10, 0)), (time(17, 0), time(20, 0))]
    print(f"\nFree time: {', '.join(format_window(window) for window in free_windows)}")
    plan = SchedulePlanningAgent(scheduler).create_plan(
        all_tasks, today, free_windows=free_windows
    )

    print(
        f"\nToday's Schedule for {owner.name} ({len(owner.list_pets())} pets): "
        f"{len(plan.schedule)} of {len(plan.due_today)} tasks fit"
    )
    for pet, task in plan.schedule:
        print(
            f"- {clock(task.due_date)} {pet.name}: {task.title} "
            f"({task.duration_minutes} min, {task.priority} priority, "
            f"{task.frequency})"
        )

    print("\nLeft out:")
    for (pet, task), reason in plan.skipped_tasks + plan.duplicate_tasks:
        print(f"- {pet.name}: {task.title} at {clock(task.due_date)}. {reason}")

    # Everything above runs without an API key; only --claude needs ANTHROPIC_API_KEY.
    if args.claude:
        print_claude_tips(plan, owner.name, today)
    else:
        print("\nTip: run `python main.py --claude` to also ask Claude to explain this plan.")


if __name__ == "__main__":
    main()

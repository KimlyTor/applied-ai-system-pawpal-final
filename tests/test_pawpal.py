from __future__ import annotations

from datetime import date, datetime, time, timedelta

from pawpal_system import (
    CareTask,
    DailyScheduler,
    Pet,
    SchedulePlanningAgent,
)


TODAY = date(2026, 10, 20)


def make_task(
    title: str,
    *,
    due_date: date = TODAY,
    due_time: time = time(9, 0),
    duration: int = 10,
    priority: str = "medium",
    frequency: str = "once",
    completed: bool = False,
) -> CareTask:
    return CareTask(
        description=title,
        title=title,
        due_date=datetime.combine(due_date, due_time),
        duration_minutes=duration,
        priority=priority,
        frequency=frequency,
        is_completed=completed,
    )


def make_assignment(task: CareTask, pet: Pet | None = None) -> tuple[Pet, CareTask]:
    return (pet or Pet(name="Mochi", species="dog"), task)


def test_mark_complete_changes_status_and_excludes_task_from_schedule() -> None:
    """Completed tasks are marked done and omitted from the daily schedule."""
    task = make_task("Walk")
    assignments = [make_assignment(task)]

    assert task.is_completed is False

    task.mark_complete()

    assert task.is_completed is True
    assert DailyScheduler().build_daily_schedule(assignments, TODAY) == []


def test_sorting_correctness_returns_tasks_in_chronological_order() -> None:
    """Tasks are returned in chronological due-date order."""
    tasks = [
        make_assignment(
            make_task("Late", due_date=TODAY + timedelta(days=2), due_time=time(15, 0))
        ),
        make_assignment(make_task("Early", due_date=TODAY, due_time=time(8, 0))),
        make_assignment(make_task("Middle", due_date=TODAY, due_time=time(11, 30))),
    ]

    ordered = DailyScheduler().sort_tasks_by_due_date(tasks)

    assert [task.title for _, task in ordered] == ["Early", "Middle", "Late"]


def test_recurrence_logic_daily_task_creates_next_day_task() -> None:
    """Completing daily occurrences creates the next task on each following day."""
    pet = Pet(name="Mochi", species="dog")
    task = make_task(
        "Morning walk", due_date=TODAY, due_time=time(7, 0), frequency="daily"
    )
    pet.add_task(task)

    pet.complete_task(task)

    next_task = pet.list_tasks()[1]
    assert task.is_completed is True
    assert next_task.is_completed is False
    assert next_task.frequency == "daily"
    assert next_task.due_date == datetime.combine(
        TODAY + timedelta(days=1), time(7, 0)
    )

    pet.complete_task(next_task)

    following_task = pet.list_tasks()[2]
    assert following_task.due_date == datetime.combine(
        TODAY + timedelta(days=2), time(7, 0)
    )


def test_recurrence_logic_weekly_task_creates_next_week_task() -> None:
    """Completing weekly occurrences creates the next task seven days later."""
    pet = Pet(name="Mochi", species="dog")
    task = make_task(
        "Weekly grooming", due_date=TODAY, due_time=time(7, 0), frequency="weekly"
    )
    pet.add_task(task)

    pet.complete_task(task)

    next_task = pet.list_tasks()[1]
    assert next_task.due_date == datetime.combine(
        TODAY + timedelta(days=7), time(7, 0)
    )

    pet.complete_task(next_task)

    following_task = pet.list_tasks()[2]
    assert following_task.due_date == datetime.combine(
        TODAY + timedelta(days=14), time(7, 0)
    )


def test_conflict_detection_flags_duplicate_times() -> None:
    """Tasks with overlapping intervals at the same start time are flagged."""
    first = make_assignment(make_task("Walk", due_time=time(9, 0), duration=30))
    second = make_assignment(make_task("Feeding", due_time=time(9, 0), duration=20))

    conflicts = DailyScheduler().find_time_conflicts([first, second], TODAY)

    assert conflicts == [(first, second)]


def test_adding_task_increases_pet_task_count() -> None:
    """Adding a task increases the pet's task list by one."""
    pet = Pet(name="Mochi", species="dog")
    task = make_task("Walk")
    initial_count = len(pet.list_tasks())

    pet.add_task(task)

    assert len(pet.list_tasks()) == initial_count + 1
    assert pet.list_tasks() == [task]


def test_planning_agent_keeps_higher_priority_task_and_reports_overlap() -> None:
    """The agent revises conflicting plans and explains the removed task."""
    high_priority = make_assignment(
        make_task("Medication", due_time=time(9, 0), duration=30, priority="high")
    )
    low_priority = make_assignment(
        make_task("Walk", due_time=time(9, 15), duration=30, priority="low")
    )

    plan = SchedulePlanningAgent().create_plan(
        [high_priority, low_priority], TODAY, available_minutes=60
    )

    assert plan.schedule == [high_priority]
    assert plan.conflicts_resolved == 1
    assert plan.skipped_tasks[0][0] == low_priority
    assert "Overlaps" in plan.skipped_tasks[0][1]
    assert DailyScheduler().find_time_conflicts(plan.schedule, TODAY) == []


def test_planning_agent_reports_tasks_that_exceed_time_budget() -> None:
    """The agent retains unscheduled tasks and explains the time constraint."""
    priority_task = make_assignment(
        make_task("Medication", duration=40, priority="high")
    )
    other_task = make_assignment(
        make_task("Walk", due_time=time(10, 0), duration=30, priority="medium")
    )

    plan = SchedulePlanningAgent().create_plan(
        [priority_task, other_task], TODAY, available_minutes=60
    )

    assert plan.schedule == [priority_task]
    assert plan.conflicts_resolved == 0
    assert plan.skipped_tasks[0][0] == other_task
    assert "time budget" in plan.skipped_tasks[0][1]


def test_planning_agent_schedules_non_overlapping_tasks_within_time_budget() -> None:
    """Tasks at 9:00 and 9:30 both fit when they take 20 minutes each."""
    walk = make_assignment(
        make_task("Walk", due_time=time(9, 0), duration=20, priority="high")
    )
    feeding = make_assignment(
        make_task("Feed", due_time=time(9, 30), duration=20, priority="high")
    )

    plan = SchedulePlanningAgent().create_plan(
        [walk, feeding], TODAY, available_minutes=60
    )

    assert plan.schedule == [walk, feeding]
    assert plan.skipped_tasks == []
    assert plan.conflicts_resolved == 0
    assert sum(task.duration_minutes for _, task in plan.schedule) == 40


def test_planning_agent_refills_time_after_skipping_overlapping_tasks() -> None:
    """A later non-overlapping task can use time left after conflict checks."""
    walk = make_assignment(
        make_task("Walk", due_time=time(9, 0), duration=20, priority="high")
    )
    overlapping_walk = make_assignment(
        make_task("Walk", due_time=time(9, 15), duration=20, priority="high")
    )
    feeding = make_assignment(
        make_task("Feed", due_time=time(9, 30), duration=20, priority="high")
    )
    overlapping_late_walk = make_assignment(
        make_task("Walk", due_time=time(9, 45), duration=20, priority="high")
    )
    back_to_back_walk = make_assignment(
        make_task("Walk", due_time=time(9, 50), duration=20, priority="high")
    )

    plan = SchedulePlanningAgent().create_plan(
        [
            walk,
            overlapping_walk,
            feeding,
            overlapping_late_walk,
            back_to_back_walk,
        ],
        TODAY,
        available_minutes=60,
    )

    assert plan.schedule == [walk, feeding, back_to_back_walk]
    assert [assignment for assignment, _ in plan.skipped_tasks] == [
        overlapping_walk,
        overlapping_late_walk,
    ]
    assert plan.conflicts_resolved == 2
    assert sum(task.duration_minutes for _, task in plan.schedule) == 60


def test_planning_agent_leaves_out_duplicate_task_instead_of_reporting_overlap() -> None:
    walk = make_task("Walk", duration=30, priority="high")
    copy = make_task("walk ", duration=30, priority="high")
    mochi = Pet(name="Mochi", species="dog", tasks=[walk, copy])

    plan = SchedulePlanningAgent().create_plan([(mochi, walk), (mochi, copy)], TODAY, 60)

    assert plan.schedule == [(mochi, walk)]
    assert plan.skipped_tasks == []
    assert plan.conflicts_resolved == 0
    assert len(plan.duplicate_tasks) == 1
    (duplicate_pet, duplicate_task), reason = plan.duplicate_tasks[0]
    assert duplicate_task is copy
    assert "Duplicate of Mochi's Walk at 9:00 AM" in reason


def test_same_title_at_different_time_or_for_other_pet_is_not_duplicate() -> None:
    morning = make_task("Walk", due_time=time(9, 0))
    evening = make_task("Walk", due_time=time(18, 0))
    other_pet_walk = make_task("Walk", due_time=time(9, 0))
    mochi = Pet(name="Mochi", species="dog", tasks=[morning, evening])
    luna = Pet(name="Luna", species="dog", tasks=[other_pet_walk])
    tasks = [(mochi, morning), (mochi, evening), (luna, other_pet_walk)]

    assert DailyScheduler().find_duplicate_tasks(tasks) == {}


def test_completed_task_is_not_counted_as_duplicate() -> None:
    done = make_task("Walk", completed=True)
    todo = make_task("Walk")
    mochi = Pet(name="Mochi", species="dog", tasks=[done, todo])

    assert DailyScheduler().find_duplicate_tasks([(mochi, done), (mochi, todo)]) == {}


def test_parse_clock_time_accepts_h_mm_with_am_pm() -> None:
    from pawpal_system import parse_clock_time

    assert parse_clock_time("9:20", "AM") == time(9, 20)
    assert parse_clock_time(" 9:20 ", "PM") == time(21, 20)
    assert parse_clock_time("12:00", "AM") == time(0, 0)
    assert parse_clock_time("12:30", "PM") == time(12, 30)
    assert parse_clock_time("11:55", "PM") == time(23, 55)


def test_parse_clock_time_rejects_other_formats() -> None:
    from pawpal_system import parse_clock_time

    for text in ["", "9", "920", "0920", "09:20", "9.20", "9:2", "9:75", "13:00", "0:30", "21:15", "9:20 pm", "abc"]:
        assert parse_clock_time(text, "AM") is None, text
    assert parse_clock_time("9:20", "XM") is None


def test_format_clock_time_round_trips() -> None:
    from pawpal_system import format_clock_time, parse_clock_time

    for value in [time(0, 0), time(9, 5), time(12, 0), time(21, 20)]:
        assert parse_clock_time(*format_clock_time(value)) == value


WINDOWS = [(time(7, 0), time(9, 0)), (time(17, 0), time(20, 0))]


def test_planning_agent_only_schedules_tasks_inside_free_windows() -> None:
    morning = make_task("Walk", due_time=time(7, 30), duration=30)
    noon = make_task("Play", due_time=time(12, 0), duration=20)
    late = make_task("Brush", due_time=time(8, 50), duration=20)  # runs past 9:00 AM
    evening = make_task("Dinner", due_time=time(17, 0), duration=15)
    mochi = Pet(name="Mochi", species="dog", tasks=[morning, noon, late, evening])
    tasks = [(mochi, task) for task in mochi.tasks]

    plan = SchedulePlanningAgent().create_plan(tasks, TODAY, free_windows=WINDOWS)

    assert [task for _, task in plan.schedule] == [morning, evening]
    skipped = {task.title: reason for (_, task), reason in plan.skipped_tasks}
    assert set(skipped) == {"Play", "Brush"}
    assert "7:00 AM–9:00 AM, 5:00 PM–8:00 PM" in skipped["Play"]
    assert plan.free_windows == WINDOWS
    assert plan.outside_window_count == 2
    assert plan.conflicts_resolved == 0


def test_free_windows_must_not_overlap_or_end_before_start() -> None:
    from pawpal_system import validate_free_windows

    assert validate_free_windows(WINDOWS) is None
    assert "overlap" in validate_free_windows([(time(7, 0), time(9, 0)), (time(8, 0), time(10, 0))])
    assert "must end after it starts" in validate_free_windows([(time(9, 0), time(7, 0))])
    assert validate_free_windows([(time(7, 0), time(9, 0)), (time(9, 0), time(10, 0))]) is None


def test_overlap_check_still_applies_inside_a_window() -> None:
    walk = make_task("Walk", due_time=time(7, 0), duration=30, priority="high")
    feed = make_task("Feed", due_time=time(7, 15), duration=10)
    mochi = Pet(name="Mochi", species="dog", tasks=[walk, feed])

    plan = SchedulePlanningAgent().create_plan([(mochi, walk), (mochi, feed)], TODAY, free_windows=WINDOWS)

    assert plan.schedule == [(mochi, walk)]
    assert "Overlaps Mochi's Walk" in plan.skipped_tasks[0][1]

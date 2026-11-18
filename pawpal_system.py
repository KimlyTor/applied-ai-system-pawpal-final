import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional


def parse_clock_time(text: str, meridiem: str) -> Optional[time]:
    """Parse a 12-hour 'H:MM' time (e.g. '9:20') with 'AM' or 'PM'; None if invalid."""
    match = re.fullmatch(r"(1[0-2]|[1-9]):([0-5]\d)", (text or "").strip())
    if not match or meridiem not in {"AM", "PM"}:
        return None
    hour = int(match[1]) % 12 + (12 if meridiem == "PM" else 0)
    return time(hour, int(match[2]))


def format_clock_time(value: time) -> tuple[str, str]:
    """Split a time into its 12-hour 'H:MM' text and 'AM'/'PM'."""
    return f"{value.hour % 12 or 12}:{value.minute:02d}", ("PM" if value.hour >= 12 else "AM")


TimeWindow = tuple[time, time]


def format_window(window: TimeWindow) -> str:
    """Format a free window as '7:00 AM–9:00 AM'."""
    start, end = window
    return f"{' '.join(format_clock_time(start))}–{' '.join(format_clock_time(end))}"


def window_minutes(window: TimeWindow) -> int:
    start, end = window
    return (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)


def validate_free_windows(windows: list[TimeWindow]) -> Optional[str]:
    """Return an error message if any window ends before it starts or windows overlap."""
    for window in windows:
        if window_minutes(window) <= 0:
            return f"The free window {format_window(window)} must end after it starts."
    ordered = sorted(windows)
    for earlier, later in zip(ordered, ordered[1:]):
        if later[0] < earlier[1]:
            return (
                f"The free windows {format_window(earlier)} and {format_window(later)} "
                "overlap. Merge them into one window."
            )
    return None


@dataclass
class Owner:
    name: str
    pets: list["Pet"]

    def __post_init__(self) -> None:
        """Ensure the owner has at least one pet."""
        if not self.pets:
            raise ValueError("An owner must have at least one pet.")

    def update_details(self, name: str) -> None:
        """Update the owner's name."""
        self.name = name

    def add_pet(self, pet: "Pet") -> None:
        """Add a pet to the owner."""
        self.pets.append(pet)

    def list_pets(self) -> list["Pet"]:
        """Return a copy of the owner's pets."""
        return self.pets.copy()

    def get_all_tasks(self) -> list[tuple["Pet", "CareTask"]]:
        """Return every pet's tasks together with the pet each task belongs to."""
        return [
            (pet, task)
            for pet in self.pets
            for task in pet.list_tasks()
        ]

    def remove_pet(self, pet: "Pet") -> None:
        """Remove a pet that belongs to the owner."""
        pet_index = next(
            (
                index
                for index, existing_pet in enumerate(self.pets)
                if existing_pet is pet
            ),
            None,
        )
        if pet_index is None:
            raise ValueError("Pet does not belong to this owner.")
        if len(self.pets) == 1:
            raise ValueError("An owner must have at least one pet.")
        del self.pets[pet_index]


@dataclass
class Pet:
    name: str
    species: str
    tasks: list["CareTask"] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate and associate this pet's initial tasks."""
        task_ids: set[int] = set()
        for task in self.tasks:
            if task._pet is not None and task._pet is not self:
                raise ValueError("Create a separate CareTask for each pet.")
            if id(task) in task_ids:
                raise ValueError("A task can only be added once to a pet.")
            task_ids.add(id(task))
        for task in self.tasks:
            task._pet = self

    def update_details(self, name: str, species: str) -> None:
        """Update the pet's name and species."""
        self.name = name
        self.species = species

    def add_task(self, task: "CareTask") -> None:
        """Attach a task instance that is tracked independently for this pet."""
        if task._pet is not None and task._pet is not self:
            raise ValueError("Create a separate CareTask for each pet.")
        if any(existing_task is task for existing_task in self.tasks):
            raise ValueError("This task is already added to this pet.")
        task._pet = self
        self.tasks.append(task)

    def list_tasks(self) -> list["CareTask"]:
        """Return a copy of the pet's tasks."""
        return self.tasks.copy()

    def remove_task(self, task: "CareTask") -> None:
        """Remove a task that belongs to this pet."""
        task_index = next(
            (
                index
                for index, existing_task in enumerate(self.tasks)
                if existing_task is task
            ),
            None,
        )
        if task_index is None:
            raise ValueError("Task does not belong to this pet.")
        del self.tasks[task_index]
        task._pet = None

    def complete_task(self, task: "CareTask") -> None:
        """Complete a task attached to this pet."""
        if not any(existing_task is task for existing_task in self.tasks):
            raise ValueError("Task does not belong to this pet.")
        task.mark_complete()


@dataclass
class CareTask:
    """A task instance with completion status tracked for one pet."""

    description: str
    title: str
    due_date: datetime
    is_completed: bool = False
    duration_minutes: int = 1
    priority: str = "medium"
    frequency: str = "once"
    _pet: "Pet | None" = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate the task's duration, priority, and frequency."""
        if self.duration_minutes <= 0:
            raise ValueError("Task duration must be greater than zero.")
        if self.priority not in {"low", "medium", "high"}:
            raise ValueError("Priority must be 'low', 'medium', or 'high'.")
        if self.frequency not in {"once", "daily", "weekly"}:
            raise ValueError("Frequency must be 'once', 'daily', or 'weekly'.")

    def is_due_on(self, selected_date: date) -> bool:
        """Check whether this task has an occurrence on the selected date."""
        first_due_date = self.due_date.date()
        if selected_date < first_due_date:
            return False
        if self.frequency == "daily":
            return True
        if self.frequency == "weekly":
            return (selected_date - first_due_date).days % 7 == 0
        return selected_date == first_due_date

    def mark_complete(self) -> None:
        """Mark this task complete and append its next occurrence if attached.

        One-time tasks and recurring tasks not attached to a pet do not create
        another task. Repeated calls on an already completed task do nothing.
        """
        if self.is_completed:
            return

        self.is_completed = True
        if self.frequency == "once" or self._pet is None:
            return

        days_until_next = 1 if self.frequency == "daily" else 7
        next_due_date = self.due_date.date() + timedelta(days=days_until_next)
        self._pet.add_task(
            CareTask(
                description=self.description,
                title=self.title,
                due_date=datetime.combine(next_due_date, self.due_date.time()),
                duration_minutes=self.duration_minutes,
                priority=self.priority,
                frequency=self.frequency,
            )
        )


TaskAssignment = tuple[Pet, CareTask]


@dataclass
class SchedulePlan:
    schedule: list[TaskAssignment]
    due_today: list[TaskAssignment]
    skipped_tasks: list[tuple[TaskAssignment, str]]
    conflicts_resolved: int
    duplicate_tasks: list[tuple[TaskAssignment, str]] = field(default_factory=list)
    free_windows: list[TimeWindow] = field(default_factory=list)
    outside_window_count: int = 0


@dataclass
class DailyScheduler:
    def get_tasks(self, owner: Owner) -> list[TaskAssignment]:
        """Retrieve all pet-task pairs through the owner's task accessor."""
        return owner.get_all_tasks()

    def sort_tasks_by_due_date(
        self, tasks: list[TaskAssignment]
    ) -> list[TaskAssignment]:
        """Sort pet-task pairs by their due dates."""
        return sorted(tasks, key=lambda assignment: assignment[1].due_date)

    def sort_by_time(self, tasks: list[TaskAssignment]) -> list[TaskAssignment]:
        """Return pet-task pairs sorted by time of day, ignoring the date."""
        return sorted(tasks, key=lambda assignment: assignment[1].due_date.time())

    def filter_tasks_by_completion_status(
        self, tasks: list[TaskAssignment], is_completed: bool
    ) -> list[TaskAssignment]:
        """Return only pet-task pairs whose completion flag matches the request."""
        return [
            assignment
            for assignment in tasks
            if assignment[1].is_completed is is_completed
        ]

    def filter_tasks_by_due_status(
        self, tasks: list[TaskAssignment], selected_date: date, status: str
    ) -> list[TaskAssignment]:
        """Return incomplete tasks classified as today, upcoming, or overdue.

        Recurring tasks are checked for an occurrence on ``selected_date`` when
        ``status`` is ``"today"``. Upcoming and overdue statuses compare the
        task's original due date with ``selected_date``.

        Raises:
            ValueError: If ``status`` is not "today", "upcoming", or "overdue".
        """
        if status not in {"today", "upcoming", "overdue"}:
            raise ValueError("Status must be 'today', 'upcoming', or 'overdue'.")

        matches = []
        for pet, task in tasks:
            if task.is_completed:
                continue

            task_date = task.due_date.date()
            if status == "today":
                is_match = task.is_due_on(selected_date)
            elif status == "upcoming":
                is_match = task_date > selected_date
            else:
                is_match = task_date < selected_date

            if is_match:
                matches.append((pet, task))

        return matches

    def build_daily_schedule(
        self,
        tasks: list[TaskAssignment],
        selected_date: date,
        available_minutes: Optional[int] = None,
    ) -> list[TaskAssignment]:
        """Prioritize incomplete tasks due today and fit them into a time limit.

        Tasks are ordered by priority (high to low), then by due datetime.
        Tasks that do not fit in the remaining minutes are skipped.

        Raises:
            ValueError: If ``available_minutes`` is negative.
        """
        due_today = self.filter_tasks_by_due_status(tasks, selected_date, "today")
        if available_minutes is not None and available_minutes < 0:
            raise ValueError("Available time cannot be negative.")

        priority_order = {"high": 0, "medium": 1, "low": 2}
        prioritized = sorted(
            due_today,
            key=lambda assignment: (
                priority_order[assignment[1].priority],
                assignment[1].due_date,
            ),
        )
        if available_minutes is None:
            return prioritized

        schedule: list[TaskAssignment] = []
        remaining_minutes = available_minutes
        for assignment in prioritized:
            duration = assignment[1].duration_minutes
            if duration <= remaining_minutes:
                schedule.append(assignment)
                remaining_minutes -= duration
        return schedule

    def find_duplicate_tasks(
        self, tasks: list[TaskAssignment]
    ) -> dict[int, TaskAssignment]:
        """Map id() of each repeated incomplete task to the first matching assignment.

        A duplicate has the same pet, title (ignoring case), due datetime, and
        frequency as an earlier incomplete task.
        """
        first_seen: dict[tuple, TaskAssignment] = {}
        duplicates: dict[int, TaskAssignment] = {}
        for pet, task in tasks:
            if task.is_completed:
                continue
            key = (id(pet), task.title.strip().casefold(), task.due_date, task.frequency)
            if key in first_seen:
                duplicates[id(task)] = first_seen[key]
            else:
                first_seen[key] = (pet, task)
        return duplicates

    def find_free_window(
        self, task: CareTask, selected_date: date, windows: list[TimeWindow]
    ) -> Optional[TimeWindow]:
        """Return the free window that fully contains the task on that day, if any."""
        start = datetime.combine(selected_date, task.due_date.time())
        end = start + timedelta(minutes=task.duration_minutes)
        for window in windows:
            window_start = datetime.combine(selected_date, window[0])
            window_end = datetime.combine(selected_date, window[1])
            if window_start <= start and end <= window_end:
                return window
        return None

    def find_time_conflicts(
        self, tasks: list[TaskAssignment], selected_date: date
    ) -> list[tuple[TaskAssignment, TaskAssignment]]:
        """Return pairs of incomplete tasks with overlapping intervals that day.

        Recurring tasks are considered if they occur on ``selected_date``.
        Overlap is checked across all pets; back-to-back tasks are not conflicts.
        """
        scheduled_tasks = [
            assignment
            for assignment in tasks
            if not assignment[1].is_completed
            and assignment[1].is_due_on(selected_date)
        ]
        conflicts = []
        for index, first_assignment in enumerate(scheduled_tasks):
            first_task = first_assignment[1]
            first_start = datetime.combine(selected_date, first_task.due_date.time())
            first_end = first_start + timedelta(minutes=first_task.duration_minutes)
            for second_assignment in scheduled_tasks[index + 1 :]:
                second_task = second_assignment[1]
                if first_task is second_task:
                    continue
                second_start = datetime.combine(
                    selected_date, second_task.due_date.time()
                )
                second_end = second_start + timedelta(
                    minutes=second_task.duration_minutes
                )
                if first_start < second_end and second_start < first_end:
                    conflicts.append((first_assignment, second_assignment))
        return conflicts


@dataclass
class SchedulePlanningAgent:
    """Create, validate, and revise a daily plan using deterministic rules."""

    scheduler: DailyScheduler = field(default_factory=DailyScheduler)

    def create_plan(
        self,
        tasks: list[TaskAssignment],
        selected_date: date,
        available_minutes: Optional[int] = None,
        free_windows: Optional[list[TimeWindow]] = None,
    ) -> SchedulePlan:
        """Select tasks by rank while checking overlaps and time as each is added.

        With ``free_windows``, a task is only scheduled if it fits entirely inside
        one window, and the budget defaults to the windows' total minutes.
        """
        free_windows = list(free_windows or [])
        if free_windows:
            window_error = validate_free_windows(free_windows)
            if window_error:
                raise ValueError(window_error)
            if available_minutes is None:
                available_minutes = sum(window_minutes(window) for window in free_windows)
        if available_minutes is None:
            raise ValueError("Provide available minutes or free windows.")
        if available_minutes < 0:
            raise ValueError("Available time cannot be negative.")

        duplicates = self.scheduler.find_duplicate_tasks(tasks)
        duplicate_tasks = []
        for pet, task in tasks:
            if id(task) in duplicates and task.is_due_on(selected_date):
                original_pet, original_task = duplicates[id(task)]
                duplicate_tasks.append(
                    (
                        (pet, task),
                        f"Duplicate of {original_pet.name}'s {original_task.title} at "
                        f"{' '.join(format_clock_time(original_task.due_date.time()))}; it was left out "
                        "so the task is not done twice.",
                    )
                )
        tasks = [assignment for assignment in tasks if id(assignment[1]) not in duplicates]

        due_today = self.scheduler.filter_tasks_by_due_status(
            tasks, selected_date, "today"
        )
        prioritized = self.scheduler.build_daily_schedule(
            tasks, selected_date, available_minutes=None
        )
        schedule: list[TaskAssignment] = []
        skipped_reasons: dict[int, str] = {}
        remaining_minutes = available_minutes
        conflicts_resolved = 0
        outside_window_count = 0
        for assignment in prioritized:
            pet, task = assignment
            if free_windows and not self.scheduler.find_free_window(
                task, selected_date, free_windows
            ):
                skipped_reasons[id(task)] = (
                    "Doesn't fit inside your free time ("
                    + ", ".join(format_window(window) for window in sorted(free_windows))
                    + "). Move it into a free window or add more free time."
                )
                outside_window_count += 1
                continue

            conflicts = self.scheduler.find_time_conflicts(
                [*schedule, assignment], selected_date
            )
            if conflicts:
                existing_assignment = next(
                    existing
                    for conflict in conflicts[0]
                    for existing in schedule
                    if existing[1] is conflict[1]
                )
                existing_pet, existing_task = existing_assignment
                skipped_reasons[id(task)] = (
                    f"Overlaps {existing_pet.name}'s {existing_task.title}. The "
                    "planner kept the higher-ranked task; change one due time "
                    "to schedule both."
                )
                conflicts_resolved += 1
                continue

            if task.duration_minutes > remaining_minutes:
                skipped_reasons[id(task)] = (
                    "Did not fit within the available time budget after "
                    "higher-ranked tasks were selected."
                )
                continue

            schedule.append((pet, task))
            remaining_minutes -= task.duration_minutes

        scheduled_ids = [id(task) for _, task in schedule]
        due_ids = {id(task) for _, task in due_today}
        skipped_ids = set(skipped_reasons)
        if (
            len(scheduled_ids) != len(set(scheduled_ids))
            or not set(scheduled_ids).issubset(due_ids)
            or set(scheduled_ids).intersection(skipped_ids)
            or set(scheduled_ids).union(skipped_ids) != due_ids
            or sum(task.duration_minutes for _, task in schedule) > available_minutes
            or self.scheduler.find_time_conflicts(schedule, selected_date)
            or (
                free_windows
                and any(
                    not self.scheduler.find_free_window(task, selected_date, free_windows)
                    for _, task in schedule
                )
            )
        ):
            raise RuntimeError("The planning agent could not validate its schedule.")

        skipped_tasks = [
            (assignment, skipped_reasons[id(assignment[1])])
            for assignment in due_today
            if id(assignment[1]) in skipped_reasons
        ]
        return SchedulePlan(
            schedule=schedule,
            due_today=due_today,
            skipped_tasks=skipped_tasks,
            conflicts_resolved=conflicts_resolved,
            duplicate_tasks=duplicate_tasks,
            free_windows=sorted(free_windows),
            outside_window_count=outside_window_count,
        )

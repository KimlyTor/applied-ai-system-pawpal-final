from datetime import date, datetime, time

import pandas as pd
import streamlit as st

from pawpal_system import (
    CareTask,
    DailyScheduler,
    Owner,
    Pet,
    SchedulePlanningAgent,
    format_clock_time,
    format_window,
    parse_clock_time,
    validate_free_windows,
    window_minutes,
)
from ai_assistant import ask_claude, get_api_key, summarize_plan

MAX_AI_CALLS_PER_SESSION = 5


def clock(value):
    """Format a time or datetime as '9:30 AM'."""
    return " ".join(format_clock_time(value.time() if isinstance(value, datetime) else value))


def clock_date(value):
    """Format a datetime as '2026-11-17 9:30 AM'."""
    return f"{value.date().isoformat()} {clock(value)}"


CLOCK_OPTIONS = [f"{hour}:{minute:02d}" for hour in [12, *range(1, 12)] for minute in range(0, 60, 5)]


def clock_time_input(label, value, key, time_container, meridiem_container, list_start=None):
    """Time dropdown (5-minute steps) that also accepts a typed H:MM, plus an AM/PM dropdown.

    The list opens at ``list_start`` (or at ``value``) and wraps around.
    Returns a time, or None if the typed text isn't in H:MM format.
    """
    clock_text, meridiem = format_clock_time(value)
    anchor = list_start or value
    start = -(-((anchor.hour % 12) * 60 + anchor.minute) // 5) % len(CLOCK_OPTIONS)
    options = CLOCK_OPTIONS[start:] + CLOCK_OPTIONS[:start]
    if clock_text not in options:
        if list_start is None:
            options = [clock_text, *options]
        else:
            # Off-step times (e.g. 9:23) go right after the nearest earlier 5-minute step.
            offset = ((value.hour % 12) * 60 + value.minute - start * 5) % 720
            options.insert(offset // 5 + 1, clock_text)
    with time_container:
        text = st.selectbox(
            label,
            options,
            index=options.index(clock_text),
            key=f"{key}_clock",
            accept_new_options=True,
            help="Pick a time, or type one like 9:20 and press Enter.",
        )
    with meridiem_container:
        meridiem = st.selectbox(
            "AM/PM", ["AM", "PM"], index=["AM", "PM"].index(meridiem), key=f"{key}_meridiem"
        )
    parsed = parse_clock_time(text, meridiem)
    if parsed is None:
        with time_container:
            st.caption(":red[Use the format 9:20 (hour 1–12, two-digit minutes).]")
    return parsed


def task_key(task):
    return (
        task["title"].strip().casefold(),
        task["due_date"],
        task["due_time"],
        task["frequency"],
    )


def duplicate_tasks(pet):
    """Return (duplicate, original) task dicts for repeated incomplete tasks of one pet."""
    first_seen = {}
    pairs = []
    for task in pet["tasks"]:
        if task.get("is_completed", False):
            continue
        key = task_key(task)
        if key in first_seen:
            pairs.append((task, first_seen[key]))
        else:
            first_seen[key] = task
    return pairs

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

# Shrink only the AM/PM dropdowns (widget keys end in "_meridiem") so "AM"/"PM" fit narrow columns.
st.markdown(
    """
<style>
[class*="st-key-"][class*="meridiem"] [data-baseweb="select"] {
    font-size: 0.8rem;
}
[class*="st-key-"][class*="meridiem"] [data-baseweb="select"] > div {
    padding-left: 0.1rem;
}
[class*="st-key-"][class*="meridiem"] [data-baseweb="select"] > div > div:first-child {
    padding-left: 0.35rem;
    padding-right: 0;
}
[class*="st-key-"][class*="meridiem"] [data-baseweb="select"] svg {
    width: 0.9rem;
    height: 0.9rem;
}
</style>
""",
    unsafe_allow_html=True,
)


st.title("🐾 PawPal+")

st.markdown(
    """
Plan pet care tasks by priority, due date, and the time available.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.
"""
    )

with st.expander("What PawPal+ can do", expanded=True):
    st.markdown(
        """
- **Track your pets and their care tasks:** add pets, then tasks with a duration, priority, due date and time, and how often they repeat (once, daily, or weekly).
- **Catch duplicates:** the same task added twice is crossed out and left out of the plan.
- **Plan around your free time:** enter the times of day you're free, and PawPal+ schedules higher-priority tasks first while avoiding overlaps.
- **Explain the plan:** see why each task was scheduled and why any task was left out.
- **Get help from Claude (optional):** Claude explains your plan, suggests new times for skipped tasks, and shares care tips. Nothing changes until you click Apply.
"""
    )

st.divider()

st.subheader("Owner and Pets")
if "owner_name_value" not in st.session_state:
    st.session_state.owner_name_value = (
        st.session_state.owner.name if "owner" in st.session_state else "Jordan"
    )
if "owner_name_editing" not in st.session_state:
    st.session_state.owner_name_editing = False

owner_name_column, owner_edit_column = st.columns([5, 1], vertical_alignment="center")
with owner_name_column:
    if st.session_state.owner_name_editing:
        owner_name = st.text_input(
            "Owner name",
            key="owner_name_input",
        )
    else:
        owner_name = st.session_state.owner_name_value
        st.metric("Owner name", owner_name)
with owner_edit_column:
    owner_edit_clicked = st.button(
        "Save" if st.session_state.owner_name_editing else "Edit",
        key="toggle_owner_name_editing",
    )

if owner_edit_clicked:
    if st.session_state.owner_name_editing:
        if not owner_name.strip():
            st.error("Enter an owner name before saving.")
        else:
            st.session_state.owner_name_value = owner_name.strip()
            st.session_state.owner_name_editing = False
            st.rerun()
    else:
        st.session_state.owner_name_input = st.session_state.owner_name_value
        st.session_state.owner_name_editing = True
        st.rerun()

if "pets" not in st.session_state:
    st.session_state.pets = []
if "next_pet_id" not in st.session_state:
    st.session_state.next_pet_id = 1

with st.form("add_pet_form", clear_on_submit=True):
    st.markdown("### Add a Pet")
    pet_name = st.text_input("Pet name", placeholder="e.g. Mochi")
    species = st.selectbox("Species", ["dog", "cat", "other"])
    add_pet = st.form_submit_button("Add pet")

if add_pet:
    if not pet_name.strip():
        st.error("Enter a pet name before adding it.")
    else:
        st.session_state.pets.append(
            {
                "id": st.session_state.next_pet_id,
                "name": pet_name.strip(),
                "species": species,
                "tasks": [],
            }
        )
        st.session_state.next_pet_id += 1

if st.session_state.pets:
    st.write("Your pets:")
    for pet in st.session_state.pets:
        st.write(f"- **{pet['name']}** ({pet['species']})")
else:
    st.info("Add a pet before adding care tasks.")

st.markdown("### Tasks")
st.caption("Add care tasks with a due date, time, frequency, duration, and priority.")

if st.session_state.pets:
    pets_by_id = {pet["id"]: pet for pet in st.session_state.pets}
    selected_task_pet_id = st.session_state.get(
        "selected_task_pet_id", next(iter(pets_by_id))
    )
    if selected_task_pet_id not in pets_by_id:
        selected_task_pet_id = next(iter(pets_by_id))
    with st.form("add_task_form", clear_on_submit=True):
        selected_pet_id = st.selectbox(
            "Assign task to",
            options=list(pets_by_id),
            index=list(pets_by_id).index(selected_task_pet_id),
            format_func=lambda pet_id: (
                f"{pets_by_id[pet_id]['name']} ({pets_by_id[pet_id]['species']})"
            ),
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            task_title = st.text_input("Task title", placeholder="e.g. Morning walk")
            duration = st.number_input(
                "Duration (minutes)", min_value=1, max_value=240, value=20
            )
        with col2:
            priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
            frequency = st.selectbox("Frequency", ["once", "daily", "weekly"])
        with col3:
            due_date = st.date_input(
                "Due date",
                value=date.today(),
                min_value=date.today(),
            )
            due_time_col, due_meridiem_col = st.columns([3, 2])
            due_time = clock_time_input(
                "Due time", time(9, 0), "due_time", due_time_col, due_meridiem_col
            )
        add_task = st.form_submit_button("Add task")

    if add_task and due_time is None:
        st.error("Enter a valid due time, like 9:20 or 2:45 pm.")
    elif add_task:
        st.session_state.selected_task_pet_id = selected_pet_id
        new_task = {
            "title": task_title.strip(),
            "duration_minutes": int(duration),
            "priority": priority,
            "due_date": due_date,
            "due_time": due_time,
            "frequency": frequency,
            "is_completed": False,
        }
        target_pet = pets_by_id[selected_pet_id]
        if not task_title.strip():
            st.error("Enter a task title before adding it.")
        elif any(
            not task.get("is_completed", False) and task_key(task) == task_key(new_task)
            for task in target_pet["tasks"]
        ):
            st.warning(
                f"{target_pet['name']} already has \"{new_task['title']}\" on "
                f"{due_date.isoformat()} at {clock(due_time)} "
                f"({frequency}), so the duplicate was not added."
            )
        else:
            target_pet["tasks"].append(new_task)

    st.markdown("### Your tasks")
    status_filter = st.selectbox(
        "Filter tasks by status",
        ["All", "Incomplete", "Completed"],
        key="task_status_filter",
    )
    task_sort = st.selectbox(
        "Sort tasks by",
        ["Due date/time", "Pet name", "Status"],
        key="task_sort",
    )
    task_entries = [
        (pet, task_index, task)
        for pet in st.session_state.pets
        for task_index, task in enumerate(pet["tasks"])
        if status_filter == "All"
        or task.get("is_completed", False) == (status_filter == "Completed")
    ]
    if task_sort == "Pet name":
        task_entries.sort(key=lambda entry: entry[0]["name"].casefold())
    elif task_sort == "Status":
        task_entries.sort(key=lambda entry: entry[2].get("is_completed", False))
    else:
        task_entries.sort(
            key=lambda entry: (
                entry[2]["due_date"],
                entry[2]["due_time"],
            )
        )

    duplicate_pairs = [
        (pet, duplicate, original)
        for pet in st.session_state.pets
        for duplicate, original in duplicate_tasks(pet)
    ]
    duplicate_ids = {id(duplicate) for _, duplicate, _ in duplicate_pairs}

    def task_status(task):
        if task.get("is_completed", False):
            return "Completed"
        if id(task) in duplicate_ids:
            return "Duplicate"
        return "Incomplete"

    def strike(text):
        # st.dataframe ignores CSS text-decoration, so draw the line with U+0336 instead.
        return "".join(character + "̶" for character in text)

    task_rows = pd.DataFrame(
        [
            {
                "Pet": pet["name"],
                "Task": strike(task["title"]) if task_status(task) == "Duplicate" else task["title"],
                "Duration": f"{task['duration_minutes']} min",
                "Priority": task["priority"].title(),
                "Frequency": task["frequency"].title(),
                "Due": datetime.combine(task["due_date"], task["due_time"]),
                "Status": task_status(task),
            }
            for pet, _, task in task_entries
        ],
        columns=[
            "Pet",
            "Task",
            "Duration",
            "Priority",
            "Frequency",
            "Due",
            "Status",
        ],
    )
    styled_task_rows = task_rows.style.map(
        lambda status: (
            "color: #2E8B57; font-weight: bold" if status == "Completed" else ""
        ),
        subset=["Status"],
    ).format(
        clock_date, subset=["Due"]
    ).apply(
        lambda row: [
            "color: #999999"
            if row["Status"] == "Duplicate"
            else ""
        ]
        * len(row),
        axis=1,
    )
    st.dataframe(styled_task_rows, width="stretch", hide_index=True)

    if duplicate_pairs:
        st.warning(
            "Some tasks are duplicates (crossed out above). They are left out of "
            "the schedule; remove them to clean up your list."
        )
        for position, (pet, duplicate, original) in enumerate(duplicate_pairs):
            text_column, button_column = st.columns([4, 1], vertical_alignment="center")
            with text_column:
                st.caption(
                    f"~~{pet['name']}: {duplicate['title']} "
                    f"{duplicate['due_date'].isoformat()} "
                    f"{clock(duplicate['due_time'])}~~ — same as "
                    f"{original['title']} at {clock(original['due_time'])}"
                )
            with button_column:
                if st.button("Remove duplicate", key=f"remove_duplicate_{pet['id']}_{position}"):
                    pet["tasks"] = [task for task in pet["tasks"] if task is not duplicate]
                    st.rerun()

    if not task_entries:
        st.caption("No tasks match this status filter.")
    else:
        incomplete_entries = [
            entry for entry in task_entries if not entry[2].get("is_completed", False)
        ]
        if incomplete_entries:
            entries_by_key = {
                (pet["id"], task_index): entry
                for entry in incomplete_entries
                for pet, task_index, _ in [entry]
            }
            selected_entry_index = st.selectbox(
                "Choose an incomplete task to mark complete",
                options=list(entries_by_key),
                format_func=lambda key: (
                    f"{entries_by_key[key][0]['name']}: "
                    f"{entries_by_key[key][2]['title']} "
                    f"({entries_by_key[key][2]['due_date'].isoformat()} "
                    f"{clock(entries_by_key[key][2]['due_time'])})"
                ),
                key=f"task_to_complete_{tuple(entries_by_key)}",
            )
            selected_entry = entries_by_key[selected_entry_index]
            pet = selected_entry[0]
            task = selected_entry[2]
            if st.button(
                "Mark complete",
                key=f"complete_{pet['id']}_{selected_entry_index[1]}",
                type="secondary",
            ):
                task_model = CareTask(
                    description=task["title"],
                    title=task["title"],
                    due_date=datetime.combine(task["due_date"], task["due_time"]),
                    duration_minutes=task["duration_minutes"],
                    priority=task["priority"],
                    frequency=task["frequency"],
                )
                pet_model = Pet(pet["name"], pet["species"], tasks=[task_model])
                pet_model.complete_task(task_model)
                task["is_completed"] = True

                if len(pet_model.tasks) > 1:
                    next_task = pet_model.tasks[-1]
                    pet["tasks"].append(
                        {
                            "title": next_task.title,
                            "duration_minutes": next_task.duration_minutes,
                            "priority": next_task.priority,
                            "frequency": next_task.frequency,
                            "due_date": next_task.due_date.date(),
                            "due_time": next_task.due_date.time(),
                            "is_completed": next_task.is_completed,
                        }
                    )
                st.rerun()
        else:
            st.caption("No incomplete tasks in this view to mark complete.")

st.divider()

st.subheader("Build Schedule")
selected_date = st.date_input(
    "Schedule date",
    value=date.today(),
    min_value=date.today(),
)
st.markdown("#### Your free time")
st.caption(
    "Add the times of day you're free. A task is only scheduled if it starts and "
    "finishes inside one of these windows."
)
if "free_windows" not in st.session_state:
    st.session_state.free_windows = [{"id": 1, "start": time(7, 0), "end": time(9, 0)}]
    st.session_state.next_window_id = 2

free_windows = []
window_inputs_valid = True
for window in list(st.session_state.free_windows):
    start_col, start_meridiem_col, end_col, end_meridiem_col, remove_col = st.columns(
        [2, 1.6, 2, 1.6, 1.6], vertical_alignment="bottom"
    )
    start = clock_time_input(
        "From", window["start"], f"window_{window['id']}_start", start_col, start_meridiem_col
    )
    end = clock_time_input(
        "To", window["end"], f"window_{window['id']}_end", end_col, end_meridiem_col
    )
    with remove_col:
        if st.button(
            "Remove",
            key=f"remove_window_{window['id']}",
            disabled=len(st.session_state.free_windows) == 1,
        ):
            st.session_state.free_windows.remove(window)
            st.rerun()
    if start is None or end is None:
        window_inputs_valid = False
        continue
    window["start"], window["end"] = start, end
    free_windows.append((start, end))

if st.button("Add window"):
    st.session_state.free_windows.append(
        {"id": st.session_state.next_window_id, "start": time(12, 0), "end": time(13, 0)}
    )
    st.session_state.next_window_id += 1
    st.rerun()

window_error = (
    validate_free_windows(free_windows)
    if window_inputs_valid
    else "Fix the free time above: use the format 9:20 for each time."
)
available_minutes = sum(window_minutes(window) for window in free_windows)
if window_error:
    st.error(window_error)
else:
    st.caption(
        f"Total free time: {available_minutes // 60} hr {available_minutes % 60} min "
        f"({', '.join(format_window(window) for window in sorted(free_windows))})"
    )

def generate_schedule(signature):
    pets = [
        Pet(
            name=pet["name"],
            species=pet["species"],
            tasks=[
                CareTask(
                    description=task["title"],
                    title=task["title"],
                    due_date=datetime.combine(task["due_date"], task["due_time"]),
                    duration_minutes=task["duration_minutes"],
                    priority=task["priority"],
                    frequency=task["frequency"],
                    is_completed=task.get("is_completed", False),
                )
                for task in pet["tasks"]
            ],
        )
        for pet in st.session_state.pets
    ]
    if "owner" not in st.session_state:
        st.session_state.owner = Owner(name=owner_name.strip(), pets=pets)
    else:
        st.session_state.owner.update_details(owner_name.strip())
        st.session_state.owner.pets = pets
    owner = st.session_state.owner
    scheduler = DailyScheduler()
    all_tasks = scheduler.get_tasks(owner)
    plan = SchedulePlanningAgent(scheduler).create_plan(
        all_tasks, selected_date, free_windows=free_windows
    )
    st.session_state.schedule_plan = plan
    st.session_state.schedule_input_signature = signature
    st.session_state.schedule_owner_name = owner.name


def schedule_signature():
    return (
        owner_name.strip(),
        selected_date,
        tuple(sorted(free_windows)),
        tuple(
            (
                pet["id"],
                pet["name"],
                pet["species"],
                tuple(
                    (
                        task["title"],
                        task["duration_minutes"],
                        task["priority"],
                        task["frequency"],
                        task["due_date"],
                        task["due_time"],
                        task.get("is_completed", False),
                    )
                    for task in pet["tasks"]
                ),
            )
            for pet in st.session_state.pets
        ),
    )


def reschedule_task(pet_name, task_title, old_due, new_date, new_time):
    for pet in st.session_state.pets:
        if pet["name"] != pet_name:
            continue
        for task in pet["tasks"]:
            if (
                task["title"] == task_title
                and not task.get("is_completed", False)
                and datetime.combine(task["due_date"], task["due_time"]) == old_due
            ):
                task["due_date"] = new_date
                task["due_time"] = new_time
                generate_schedule(schedule_signature())
                return True
    return False


def apply_new_time(pet_name, task_title, old_due, new_date, new_time):
    """Move a task and remember the change so the result can be shown in place."""
    if not reschedule_task(pet_name, task_title, old_due, new_date, new_time):
        return False
    records = st.session_state.setdefault("applied_reschedules", [])
    new_due = datetime.combine(new_date, new_time)
    earlier = next(
        (
            record
            for record in records
            if record["pet"] == pet_name
            and record["title"] == task_title
            and record["new"] == old_due
        ),
        None,
    )
    if earlier:
        earlier["new"] = new_due
    else:
        records.append({"pet": pet_name, "title": task_title, "old": old_due, "new": new_due})
    return True


schedule_input_signature = schedule_signature()

if st.button("Generate schedule"):
    st.session_state.pop("schedule_plan", None)
    if not owner_name.strip():
        st.error("Enter an owner name to generate a schedule.")
    elif not st.session_state.pets:
        st.error("Add at least one pet before generating a schedule.")
    elif window_error:
        st.error("Fix your free time windows before generating a schedule.")
    else:
        st.session_state.applied_reschedules = []
        generate_schedule(schedule_input_signature)

if st.session_state.get("schedule_input_signature") == schedule_input_signature:
    plan = st.session_state.get("schedule_plan")
    if plan is not None:
        schedule = plan.schedule
        due_today = plan.due_today
        applied_reschedules = [
            record
            for record in st.session_state.get("applied_reschedules", [])
            if any(
                pet["name"] == record["pet"]
                and task["title"] == record["title"]
                and not task.get("is_completed", False)
                and datetime.combine(task["due_date"], task["due_time"]) == record["new"]
                for pet in st.session_state.pets
                for task in pet["tasks"]
            )
        ]
        moved_from = {
            (record["pet"], record["title"], record["new"]): record["old"]
            for record in applied_reschedules
        }
        def tasks(count):
            return f"{count} task{'s' if count != 1 else ''}"

        if plan.skipped_tasks:
            other_count = (
                len(plan.skipped_tasks) - plan.conflicts_resolved - plan.outside_window_count
            )
            reasons = [
                f"{tasks(count)} {text}"
                for count, text in [
                    (plan.outside_window_count, "outside your free time"),
                    (plan.conflicts_resolved, "overlapping another task"),
                    (other_count, "over the time limit"),
                ]
                if count
            ]
            st.warning(
                f"{tasks(len(schedule))} of {len(due_today)} fit your plan. Left out: "
                + ", ".join(reasons)
                + ". See the reasons below, and reschedule them under Ask Claude for tips."
            )
        elif due_today:
            st.success(
                f"Plan checked: all {tasks(len(schedule))} fit inside your free time, "
                "with no overlapping tasks."
            )

        if schedule:
            st.markdown(
                f"### Daily plan for {st.session_state.schedule_owner_name}"
            )
            for pet, task in schedule:
                task_window = DailyScheduler().find_free_window(
                    task, selected_date, plan.free_windows
                )
                old_due = moved_from.get((pet.name, task.title, task.due_date))
                st.write(
                    f"- **{clock(task.due_date)} — {pet.name}: "
                    f"{task.title}** "
                    f"({task.duration_minutes} min, {task.priority} priority, "
                    f"{task.frequency})"
                    + (
                        f" :green[· rescheduled from {clock(old_due)}]"
                        if old_due
                        else ""
                    )
                )
                st.caption(
                    f"Why it's scheduled: It is due at "
                    f"{clock(task.due_date)} on "
                    f"{selected_date.isoformat()}. The planner considers "
                    "higher-priority tasks first, then earlier due times, and "
                    "avoids overlapping tasks. "
                    f"It fits inside your {format_window(task_window)} free window."
                )
        elif not due_today:
            st.info("No incomplete tasks due on this date.")

        if plan.skipped_tasks:
            with st.expander("Tasks needing more time or rescheduling", expanded=True):
                for (pet, task), reason in plan.skipped_tasks:
                    st.markdown(f"**{pet.name}: {task.title}** — due {clock_date(task.due_date)}")
                    st.caption(reason)
                st.caption(
                    "To move one of these tasks, use Reschedule skipped tasks under "
                    "Ask Claude for tips below."
                )

        if plan.duplicate_tasks:
            st.info(
                "Left out as duplicates (remove them under Your tasks):\n"
                + "\n".join(
                    f"- {pet.name}: {task.title} at {clock(task.due_date)}. {reason}"
                    for (pet, task), reason in plan.duplicate_tasks
                )
            )

        if plan.due_today or applied_reschedules:
            st.markdown("### 🤖 Ask Claude for tips")
            st.caption(
                "Claude explains the plan above and suggests new times for skipped "
                "tasks. Nothing changes until you click Apply."
            )
            ai_calls = st.session_state.setdefault("ai_calls", 0)
            # Suggestions are keyed per task (not per plan) so applying one keeps the others.
            saved_suggestions = st.session_state.setdefault("reschedule_suggestions", {})

            def suggestion_key(pet, task):
                return (pet.name, task.title, task.due_date)

            cache_key = repr(schedule_input_signature)
            last_tips = st.session_state.get("claude_tips")
            tips_are_current = last_tips is not None and last_tips["signature"] == cache_key

            if plan.due_today and not (tips_are_current and last_tips["reply"].used_ai):
                if ai_calls >= MAX_AI_CALLS_PER_SESSION:
                    st.info(
                        f"You've used all {MAX_AI_CALLS_PER_SESSION} Claude requests for "
                        "this session (a limit to save credit), so Claude can't explain "
                        "this updated plan. Refresh the page to start a new session. You "
                        "can still reschedule tasks yourself below."
                    )
                elif st.button(
                    "Get Claude's tips",
                    help=(
                        f"{MAX_AI_CALLS_PER_SESSION - ai_calls} of "
                        f"{MAX_AI_CALLS_PER_SESSION} Claude requests left this session."
                    ),
                ):
                    summary = summarize_plan(
                        plan,
                        st.session_state.schedule_owner_name,
                        selected_date,
                        int(available_minutes),
                    )
                    with st.spinner("Asking Claude..."):
                        reply = ask_claude(plan, summary, selected_date, get_api_key())
                    if reply.used_ai:
                        st.session_state.ai_calls = ai_calls + 1
                        for ((pet, task), _), suggestion in zip(
                            plan.skipped_tasks, reply.suggestions
                        ):
                            if suggestion:
                                saved_suggestions[suggestion_key(pet, task)] = suggestion
                    last_tips = {"signature": cache_key, "reply": reply}
                    st.session_state.claude_tips = last_tips
                    tips_are_current = True

            if last_tips is not None and not tips_are_current:
                # An answer about an older plan would be misleading, so it isn't shown.
                if st.session_state.ai_calls < MAX_AI_CALLS_PER_SESSION:
                    st.caption(
                        "Your plan changed since Claude's last answer. Click "
                        "Get Claude's tips for an updated explanation."
                    )
                last_tips = None

            if last_tips is not None:
                reply = last_tips["reply"]
                if reply.note:
                    st.warning(reply.note)
                st.markdown(f"**Why this plan works**  \n{reply.text}")

            if plan.skipped_tasks or applied_reschedules:
                st.markdown("**Reschedule skipped tasks**")
                for record in applied_reschedules:
                    label = (
                        f"**{record['pet']}: {record['title']}** moved from "
                        f"{clock_date(record['old'])} to "
                        f"**{clock_date(record['new'])}**"
                    )
                    still_skipped = next(
                        (
                            reason
                            for (pet, task), reason in plan.skipped_tasks
                            if pet.name == record["pet"]
                            and task.title == record["title"]
                            and task.due_date == record["new"]
                        ),
                        None,
                    )
                    if (record["pet"], record["title"], record["new"]) in {
                        (pet.name, task.title, task.due_date) for pet, task in schedule
                    }:
                        st.success(f"✓ {label} — now in your plan.")
                    elif still_skipped:
                        st.warning(f"{label}, but it still doesn't fit: {still_skipped}")
                    else:
                        st.success(
                            f"✓ {label} — it's no longer due on "
                            f"{selected_date.isoformat()}, so it's off this day's plan."
                        )

                if plan.skipped_tasks:
                    has_suggestions = any(
                        suggestion_key(pet, task) in saved_suggestions
                        for (pet, task), _ in plan.skipped_tasks
                    )
                    st.caption(
                        "Claude's suggested time is filled in. Change it if you like, "
                        "then click Apply."
                        if has_suggestions
                        else "Click Get Claude's tips for suggested times, or enter a "
                        "new date and time yourself and click Apply."
                    )

                for position, ((pet, task), reason) in enumerate(plan.skipped_tasks):
                    suggestion = saved_suggestions.get(suggestion_key(pet, task))
                    st.markdown(f"**{pet.name}: {task.title}** — now {clock_date(task.due_date)}")
                    if suggestion:
                        st.caption(
                            f"Claude suggests {suggestion.suggested_date.isoformat()} "
                            f"{clock(suggestion.suggested_time)} — {suggestion.reason}"
                        )
                    widget_key = (
                        f"reschedule_{position}_{pet.name}_{task.title}_"
                        f"{task.due_date.isoformat()}_"
                        + (
                            f"{suggestion.suggested_date.isoformat()}T"
                            f"{suggestion.suggested_time.strftime('%H%M')}"
                            if suggestion
                            else "manual"
                        )
                    )
                    date_col, time_col, meridiem_col, apply_col = st.columns(
                        [3, 2.5, 2.5, 2], vertical_alignment="bottom"
                    )
                    with date_col:
                        new_date = st.date_input(
                            "New date",
                            value=max(
                                suggestion.suggested_date if suggestion else task.due_date.date(),
                                date.today(),
                            ),
                            min_value=date.today(),
                            key=f"{widget_key}_date",
                        )
                    new_time = clock_time_input(
                        "New time",
                        suggestion.suggested_time if suggestion else time(6, 0),
                        f"{widget_key}_time",
                        time_col,
                        meridiem_col,
                        list_start=time(6, 0),
                    )
                    with apply_col:
                        if st.button("Apply", key=f"{widget_key}_apply", type="primary"):
                            if new_time is None:
                                st.error("Enter a valid time first.")
                            elif apply_new_time(
                                pet.name, task.title, task.due_date, new_date, new_time
                            ):
                                st.rerun()
                            else:
                                st.error("Could not find that task to update.")

            if last_tips is not None:
                reply = last_tips["reply"]
                if reply.tips:
                    st.markdown(
                        "**Tips**\n" + "\n".join(f"- {tip}" for tip in reply.tips)
                    )
                if reply.used_ai:
                    st.caption(
                        f"{reply.input_tokens} input + {reply.output_tokens} output "
                        f"tokens · about ${reply.estimated_cost_usd:.4f} · "
                        f"Claude requests this session: {st.session_state.ai_calls}/"
                        f"{MAX_AI_CALLS_PER_SESSION}."
                    )

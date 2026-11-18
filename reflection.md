# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
    - The UML design is based on an owner who can have one or more pets. Each pet has its own care tasks, and a **DailyScheduler** gathers and organizes tasks across all the pets.

- What classes did you include, and what responsibilities did you assign to each?

    - **Owner:** Stores identifying information and manages a list of pets.
    - **Pet:** Stores identifying information and manages its care tasks.
    - **CareTask:** Stores a description, title, due date, and completion status; it can be marked complete.
    - **DailyScheduler:** Gathers tasks across pets, sorts and filters them by due date, and builds a daily schedule.

**b. Design changes**

- Did your design change during implementation?
    - Yes.
- If yes, describe at least one change and why you made it.

    I clarified how pets, tasks, and owners relate to each other:
    - Each task belongs to one pet, so completion is tracked independently.
    - Scheduled tasks stay paired with their pets, so it's clear whose task it is.
    - Each owner must have at least one pet, matching the UML relationship.

    In the final version, I also:
    - Added a **SchedulePlanningAgent** that builds the plan, checks it, and records why each skipped task was left out.
    - Replaced the "available minutes" budget with **free time windows** (for example 7:00–9:00 AM), because owners are free at certain times of day, not for a number of minutes.
    - Added **duplicate detection**, so the same task added twice isn't planned twice.
    - Added a **Claude coach** that explains the plan and suggests new times for skipped tasks. The owner has to approve a suggestion before anything changes.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?

    The scheduler considers:
    - Whether a task is unfinished and due on the selected day.
    - Task priority and due time, with higher-priority tasks scheduled first.
    - The owner's free time windows; a task is only scheduled if it starts and finishes inside one.
    - Whether a task overlaps a task already in the plan.
    - Whether a task is one-time, daily, or weekly.
    - Whether a task is a duplicate of one already added.

- How did you decide which constraints mattered most?

    Tasks due that day come first because the scheduler makes a plan for one specific day. Only unfinished tasks are included because a completed task does not need to be scheduled again. Higher-priority tasks come first; if two tasks have the same priority, the one due earlier is scheduled first. The free time windows keep the plan realistic, because a task can only happen when the owner is actually free.

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.

    The `filter_tasks_by_due_status` method uses explicit if/elif branches instead of a compact dictionary of lambdas. This takes a few more lines, but makes each status check easier to follow.

    Another tradeoff is that the rule-based planner decides the schedule and Claude only gives advice. This keeps every plan valid and testable, but Claude can't rearrange the whole day; it can only suggest new times for skipped tasks, and the owner decides whether to use them.

- Why is that tradeoff reasonable for this scenario?

    The logic in `filter_tasks_by_due_status` is straightforward to understand and maintain, especially because "today" uses recurrence-aware logic while "upcoming" and "overdue" compare dates. The small amount of extra code is worthwhile for clarity.

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?

    I used AI as a step-by-step helper. While working on `pawpal_uml.mmd`, I asked it to help identify the classes, their responsibilities, and how they relate to each other. Then I used the UML to guide the Python classes and scheduling logic in `pawpal_system.py`, asking for explanations when I was unsure how to implement part of the design. When issues came up, I shared the relevant code or error, asked AI to help find the cause, and used its suggestions to improve the code.

    For the final version, I used an AI coding assistant (Claude Code) to build bigger features, like free time windows, duplicate detection, and the Claude coach. I described what I wanted, the assistant made the changes and ran the tests, and then I tried the app in the browser and reported anything that looked wrong. I also added Claude into the app itself through the Anthropic API, so it can explain the plan and suggest new times for skipped tasks.

- What kinds of prompts or questions were most helpful?

    Specific questions about how the UML should map to the Python classes and what a piece of code did were most helpful. I also asked for explanations comparing a class before and after a suggested change, so I could understand its purpose and decide whether the change made sense before using it. Adding project details in follow-up questions helped AI give more relevant answers.

    Describing exactly what I saw in the app, like "the AM/PM is cut off to A…" or "the tip says 9:20 but the suggestion says 9:30", helped the assistant find the real cause instead of guessing.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.

    One example was when the suggested `Owner` and `DailyScheduler` classes did not fully meet the project requirements. Instead of using them as written, I asked AI to regenerate the classes to better match what the project needed.

    Another example was when the AM/PM dropdown was cut off. The assistant's first fix moved the AM/PM box below the time box, but that broke the layout of the form. I rejected it and asked for smaller text instead, so it could stay beside the time.

- How did you evaluate or verify what the AI suggested?

    I checked that `Owner` managed its pets and provided their tasks, and that `DailyScheduler` used those tasks to build a schedule. I also reviewed how the classes worked with `Pet` and `CareTask` to make sure the revised design fit the rest of the implementation. For the final features, I ran the tests and also used the app myself in the browser, because some problems, like the cut-off AM/PM, only showed up there.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?

    Tested behaviors (25 tests):
    - Task completion and adding tasks
    - Chronological sorting
    - Daily and weekly recurrence
    - Conflict detection
    - Priority ordering and skipped tasks
    - Free time windows
    - Duplicate tasks
    - Typed times like 9:20 with AM/PM
    - The Claude coach, using a fake client so tests don't cost anything, including what happens without an API key

- Why were these tests important?

    They check key scheduler behaviors, including task ordering, recurrence, completion, free time, and conflict detection. The Claude tests make sure the app still works when Claude isn't available.

**b. Confidence**

- How confident are you that your scheduler works correctly?

    I'm very confident in the tested behaviors. The test suite grew from 6 to 25 tests, but the tests can't judge how good Claude's suggestions are, so I also checked a few real Claude answers by hand.

- What edge cases would you test next if you had more time?

    I would test:
    - Back-to-back tasks
    - Invalid task details
    - Completing a recurring task more than once
    - Free time windows that cross midnight

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

    I’m most satisfied that I caught and fixed a bug in the daily and weekly recurrence behavior. The next occurrence wasn’t being scheduled correctly, so I tested the logic and confirmed daily tasks recur the next day and weekly tasks recur seven days later.

    I'm also satisfied with how the Claude coach turned out: it explains the plan and suggests new times, but the owner always decides, so the schedule can't be broken by a bad AI answer.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

    If I had another iteration, I would add persistent storage so pet and task information is saved between sessions. I would also add tests for the edge cases above and check Claude's suggestions on many more plans.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

    I learned that planning the classes and their relationships before coding makes a system easier to understand and implement. Creating a UML (Unified Modeling Language) class diagram helped me visualize how `Owner`, `Pet`, `CareTask`, and `DailyScheduler` work together and gave me a guide to follow as I built the code.

    I also learned that AI works best as an advisor with a human approving its suggestions, and that I still need to check its work the way a user would, not just with automated tests.

# Kirah Weekly Client Scheduler

A private, administrator-only recurring weekly scheduler for one provider and approximately 10–12 clients.

This complete download includes a ready-to-use `scheduler.db` with eight sample clients and nine sample appointments, so the website is populated the first time it opens.

**Project build:** `2026.08.03-v2`

## Schedule setup

- Sunday through Thursday
- Afternoon appointments: 2:00–6:00 PM
- Evening appointments: 8:00–11:00 PM
- Every session is 30 minutes
- Each client can need 1–5 sessions per week
- Multiple sessions for one client must be on different days
- One provider means only one client can use a time slot

## Website pages

1. **Schedule** — the approved schedule currently in use
2. **Add Client** — client details and a weekly availability calendar
3. **Clients** — view, edit, or request deletion of a client
4. **Draft Schedule** — review all unapproved changes together
5. **Settings** — choose two preferred free evenings

## Availability wording

The website uses three simple choices:

- **Best time**
- **Also works**
- **Not available**

The database continues to store the older internal values `optimal` and `secondary` so existing databases upgrade safely. Those technical words are not shown to the administrator.

## Add Client logic

When a new client is saved, the scheduler checks the complete approved schedule.

### Fits without moving anyone

When there is no existing draft and no approved appointment needs to move, the client is added immediately.

Possible responses:

- **Fits perfectly** — every session uses a Best Time
- **Fits well** — at least one session uses Also Works
- **Fits, but uses another evening** — the client fits, but fewer than two evenings remain completely free

### Fits only after moving someone

The client is saved as **Waiting for a time**, and one combined Draft Schedule is created. The approved schedule does not change until the draft is approved.

Response:

- **Fits with changes**

### No time works

The client is still saved as **Waiting for a time**, but is not added to the approved schedule or future scheduling checks automatically.

Response:

- **No time found**

A waiting client can later be edited and tried again. An older waiting client cannot secretly block a different new client.

## Edit Client logic

The Edit Client button allows changes to:

- Name
- Location
- Notes
- Sessions each week
- Best Times
- Also Works times

Edits always go into the Draft Schedule. The approved client information and appointments remain unchanged until the whole draft is approved.

If the edited availability cannot work, the app shows:

> These changes do not fit. Nothing was changed.

When the edited client has a locked appointment, that same client's appointment may move because of the edit. The replacement appointment remains locked after approval. Locks belonging to other clients cannot move.

## Delete Client logic

The website uses **Delete Client**, never “deactivate.”

Deletion is permanent, but it first enters the Draft Schedule. The client and appointments remain untouched until the entire draft is approved. After approval, the client and all related records are fully deleted. The same name may then be used for a new client.

## One combined Draft Schedule

There is never a stack of conflicting proposals. The app keeps:

- One **Approved Schedule**
- One combined **Draft Schedule**

The draft can contain several requested changes at once:

- Add a client
- Edit a client
- Delete a client
- Improve the schedule

Every new request recalculates the complete draft. The administrator can:

- Approve the entire draft
- Remove one requested change and recalculate the rest
- Discard the entire draft

Nothing in the approved schedule changes until approval.

## Scheduling priorities

### Rules that may never be broken

1. Every scheduled session is exactly 30 minutes.
2. Only one client may use a time slot.
3. A client can use only a Best Time or Also Works time selected for that client.
4. Every client receives the required number of weekly sessions.
5. Multiple sessions for one client occur on different days.
6. Appointments occur only Sunday–Thursday from 2:00–6:00 PM or 8:00–11:00 PM.
7. A locked appointment stays at its exact time, except when that same client is intentionally edited.
8. Weekly sessions cannot exceed the number of different available days.
9. Client names must be unique, ignoring capitalization.

### Choices optimized in order

For normal additions and edits:

1. Move as few appointments belonging to unchanged clients as possible.
2. Keep the edited client's current appointments when they still work.
3. Protect the two preferred free evenings.
4. Keep at least two evenings completely free.
5. Use Best Times instead of Also Works.
6. Keep appointments together with as few gaps as possible.
7. Use fewer separate afternoon/evening blocks.
8. Create extra free evenings only as a final tie-breaker.

This means the scheduler will not move an existing appointment only to save an evening. It also will not sacrifice a Best Time merely to create a third or fourth free evening after the two-evening goal is already met.

For **Improve Schedule**, the administrator explicitly allows rearrangement. The solver then prioritizes the selected free evenings, at least two free evenings, Best Times, and tighter clustering before minimizing the number of moves. Every move is shown in the draft before approval.

## How clustering works

Each day has two separate blocks:

- Afternoon: 2:00–6:00 PM
- Evening: 8:00–11:00 PM

The 6:00–8:00 PM break is never counted as a gap.

The solver counts each run of consecutive appointments as one segment:

- 2:00, 2:30, 3:00 = **one segment**
- 2:00, 3:00, 4:00 = **three segments**

When higher-priority rules are tied, the schedule with fewer segments is selected.

## Schedule display

The weekly schedule boxes show only the client's name. Clicking a name opens:

- Location
- Notes
- Every weekly appointment
- Lock or Unlock controls for each exact appointment

## Database structure

### `clients`

- Client name, location, and notes
- Sessions per week
- `active` or `waiting` status
- Created and updated times

### `client_availability`

- Client
- Time slot
- Best Time or Also Works internal value

### `assignments`

- Approved client appointment
- Exact slot
- Lock status

### `settings`

- First preferred free evening
- Second preferred free evening

### `draft_changes`

- One pending add, edit, or delete request per client
- Proposed client information

### `draft_change_availability`

- Proposed Best Time and Also Works choices for a draft add/edit

### `draft_assignments`

- The complete recalculated draft schedule
- Lock status that will apply after approval

### `draft_meta`

- Draft result message
- Number of free evenings
- Number of moves
- Whether Improve Schedule was requested
- Project build number

The app automatically adds the new tables and columns when opening a database from an earlier version.

## Included sample database

The project includes `scheduler.db` with:

- Eight sample clients
- Nine recurring weekly appointments
- One client with two sessions on different days
- Afternoon and evening examples
- One locked appointment example
- Wednesday and Thursday selected as the preferred free evenings
- No pending Draft Schedule

The sample names, locations, and notes can be edited or permanently deleted through the website.

To restore the original sample data later, first understand that this erases the current database, then run:

```bash
python seed_demo_database.py --force
```

To start with no clients, the following command first renames the current database as a timestamped backup and then creates a blank one:

```bash
python create_empty_database.py --force
```

## Install and run

Python 3.11–3.13 is recommended.

```bash
python -m venv .venv
```

Activate the environment, then install:

```bash
python -m pip install -r requirements.txt
```

Verify the folder:

```bash
python verify_project.py
```

Run all tests:

```bash
python -m pytest
```

Start the app:

```bash
python -m streamlit run app.py
```

## Updating through GitHub

Do not upload only one Python file. All files in this build must stay together.

1. Open the repository on GitHub.
2. Open the branch menu near the upper-left corner.
3. Type a new branch name such as `scheduler-v2`.
4. Select **Create branch: scheduler-v2 from main**.
5. Download and unzip this project on your computer.
6. On the new GitHub branch, choose **Add file → Upload files**.
7. Drag in **everything inside the unzipped folder**, including `scheduler.db`, the Python files, and the `tests` folder.
8. Commit all uploaded files to the new branch.
9. Open a Codespace from that branch and run `python verify_project.py`.

Because this edition is intended as a complete first setup, `scheduler.db` is included and should be uploaded. The database contains only the sample clients listed above.

After real client data has been entered, back up the database before replacing or resetting it:

```bash
cp scheduler.db scheduler_backup.db
```

## Main project files

- `app.py` — Streamlit interface and light blue/gray design
- `constants.py` — days, times, slot keys, and friendly labels
- `database.py` — SQLite schema, migrations, approved schedule, and draft storage
- `scheduler_service.py` — add/edit/delete/draft decision workflow
- `solver.py` — Google OR-Tools scheduling model
- `project_version.py` — prevents mixed file versions
- `verify_project.py` — checks file consistency, compilation, and the included database
- `scheduler.db` — ready-to-use SQLite database with sample clients and appointments
- `seed_demo_database.py` — safely rebuilds the included sample database when run with `--force`
- `create_empty_database.py` — backs up the current database and creates an empty one
- `tests/` — database, workflow, optimization, migration, seed-data, and wording tests
- `.gitignore` — ignores database backups and temporary files while allowing `scheduler.db` into GitHub

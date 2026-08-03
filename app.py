from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import database
import scheduler_service as service
from constants import (
    AFTERNOON_TIMES,
    APP_BUILD,
    AVAILABILITY_OPTIONS,
    DAYS,
    EVENING_TIMES,
    LABEL_TO_PREFERENCE,
    PREFERENCE_LABELS,
    PREFERENCE_UNAVAILABLE,
    SLOT_BY_KEY,
    SLOT_LABEL_TO_KEY,
    SLOT_KEY_TO_LABEL,
    TIMES,
)
from project_version import EXPECTED_BUILD

DB_PATH = Path(__file__).with_name("scheduler.db")

st.set_page_config(
    page_title="Weekly Client Scheduler",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded",
)

database.init_db(DB_PATH)

st.markdown(
    """
    <style>
    :root {
        --ink: #233142;
        --muted: #6f7f91;
        --line: #dce5ee;
        --panel: #ffffff;
        --wash: #f3f7fb;
        --blue: #5d88b3;
        --blue-dark: #426b94;
        --blue-soft: #e8f1f8;
        --gray-soft: #edf2f6;
        --danger: #a94f58;
    }
    .stApp { background: var(--wash); color: var(--ink); }
    .block-container { max-width: 1500px; padding-top: 1.5rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: var(--ink); letter-spacing: -0.02em; }
    [data-testid="stSidebar"] { background: #eaf1f7; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] .stRadio label { padding: .38rem .55rem; border-radius: 9px; }
    div[data-testid="stForm"], div[data-testid="stExpander"], .clean-card {
        background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
        padding: 1rem; box-shadow: 0 5px 18px rgba(48, 73, 97, .06);
    }
    .eyebrow { color: var(--blue-dark); font-size: .78rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: .12em; }
    .muted { color: var(--muted); }
    .schedule-time { color: var(--muted); font-weight: 650; padding-top: .55rem; }
    .empty-slot { height: 2.65rem; border: 1px dashed #d7e1ea; border-radius: 9px;
        background: #f9fbfd; }
    .section-gap { height: .75rem; }
    .status-pill { display: inline-block; padding: .28rem .62rem; border-radius: 999px;
        background: var(--blue-soft); color: var(--blue-dark); font-size: .82rem; font-weight: 700; }
    div.stButton > button { border-radius: 9px; border: 1px solid #cddae6; }
    div.stButton > button[kind="primary"] { background: var(--blue-dark); border-color: var(--blue-dark); }
    div[data-testid="stDataEditor"] { background: white; border-radius: 12px; overflow: hidden; }
    .draft-note { background: #eef5fa; border-left: 4px solid var(--blue); padding: .8rem 1rem;
        border-radius: 8px; color: var(--ink); }
    .availability-day { text-align: center; font-weight: 700; padding: .45rem 0 .55rem; }
    .st-key-add_availability_grid div.stButton > button { min-height: 2.65rem; }
    .st-key-add_availability_grid div.stButton > button[kind="primary"] {
        background: #3f5368; border-color: #3f5368; color: white;
    }
    .st-key-add_availability_grid div.stButton > button[kind="secondary"] {
        background: #aebfce; border-color: #9eafbd; color: #1f3040;
    }
    .st-key-add_availability_grid div.stButton > button[kind="tertiary"] {
        background: #f7f9fb; border: 1px solid #dce5ee; color: #6f7f91;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if APP_BUILD != EXPECTED_BUILD:
    st.error("Project files are from different versions. Upload all files together.")
    st.stop()


def show_result(result: service.ActionResult) -> None:
    if result.success:
        st.success(result.category)
        st.write(result.message)
        if result.draft_updated:
            st.info("Review everything on the **Draft Schedule** page before approving it.")
    else:
        st.error(result.category)
        st.write(result.message)


def availability_dataframe(saved: dict[str, str] | None = None) -> pd.DataFrame:
    saved = saved or {}
    rows: list[dict] = []
    for time_label in TIMES:
        row = {"Time": time_label}
        for day in DAYS:
            slot_key = SLOT_LABEL_TO_KEY[f"{day} {time_label}"]
            preference = saved.get(slot_key, PREFERENCE_UNAVAILABLE)
            row[day] = PREFERENCE_LABELS[preference]
        rows.append(row)
    return pd.DataFrame(rows)


def render_availability_editor(
    *,
    saved: dict[str, str] | None,
    key: str,
) -> dict[str, str]:
    st.caption(
        "Choose **Best time** or **Also works**. Leave all other boxes as **Not available**."
    )
    frame = availability_dataframe(saved)
    edited = st.data_editor(
        frame,
        key=key,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=["Time"],
        column_config={
            "Time": st.column_config.TextColumn("Time", width="small"),
            **{
                day: st.column_config.SelectboxColumn(
                    day,
                    options=AVAILABILITY_OPTIONS,
                    required=True,
                    width="medium",
                )
                for day in DAYS
            },
        },
    )

    availability: dict[str, str] = {}
    for _, row in edited.iterrows():
        time_label = str(row["Time"])
        for day in DAYS:
            label = str(row[day])
            preference = LABEL_TO_PREFERENCE[label]
            if preference != PREFERENCE_UNAVAILABLE:
                slot_key = SLOT_LABEL_TO_KEY[f"{day} {time_label}"]
                availability[slot_key] = preference
    return availability


def render_add_availability_grid() -> dict[str, str]:
    """Render the Add Client availability as color-coded, cycling buttons."""
    state_key = "add_availability_values"
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            slot_key: PREFERENCE_UNAVAILABLE for slot_key in SLOT_BY_KEY
        }

    st.caption(
        "Click a box to cycle through **Not available**, **Best time**, and **Also works**."
    )
    values = st.session_state[state_key]
    cycle = {
        PREFERENCE_UNAVAILABLE: "optimal",
        "optimal": "secondary",
        "secondary": PREFERENCE_UNAVAILABLE,
    }
    button_types = {
        PREFERENCE_UNAVAILABLE: "tertiary",
        "optimal": "primary",
        "secondary": "secondary",
    }

    with st.container(key="add_availability_grid"):
        header = st.columns([1.05, 1, 1, 1, 1, 1])
        header[0].markdown('<div class="availability-day">Time</div>', unsafe_allow_html=True)
        for index, day in enumerate(DAYS, start=1):
            header[index].markdown(
                f'<div class="availability-day">{day}</div>', unsafe_allow_html=True
            )

        for time_label in TIMES:
            columns = st.columns([1.05, 1, 1, 1, 1, 1])
            columns[0].markdown(
                f'<div class="schedule-time">{time_label}</div>', unsafe_allow_html=True
            )
            for day_index, day in enumerate(DAYS, start=1):
                slot_key = SLOT_LABEL_TO_KEY[f"{day} {time_label}"]
                preference = values[slot_key]
                if columns[day_index].button(
                    PREFERENCE_LABELS[preference],
                    key=f"add_slot_{slot_key}",
                    type=button_types[preference],
                    use_container_width=True,
                ):
                    values[slot_key] = cycle[preference]
                    st.rerun()

    return {
        slot_key: preference
        for slot_key, preference in values.items()
        if preference != PREFERENCE_UNAVAILABLE
    }


def assignment_lookup(assignments: dict[int, list[dict]]) -> dict[str, dict]:
    return {
        assignment["slot_key"]: assignment
        for values in assignments.values()
        for assignment in values
    }


def render_schedule_grid(
    assignments: dict[int, list[dict]],
    *,
    key_prefix: str,
    clickable: bool,
) -> None:
    lookup = assignment_lookup(assignments)
    header = st.columns([1.05, 1, 1, 1, 1, 1])
    header[0].markdown("**Time**")
    for index, day in enumerate(DAYS, start=1):
        header[index].markdown(f"**{day}**")

    for time_label in TIMES:
        if time_label == EVENING_TIMES[0]:
            st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
            st.caption("Evening")
        columns = st.columns([1.05, 1, 1, 1, 1, 1])
        columns[0].markdown(
            f'<div class="schedule-time">{time_label}</div>', unsafe_allow_html=True
        )
        for day_index, day in enumerate(DAYS, start=1):
            slot_key = SLOT_LABEL_TO_KEY[f"{day} {time_label}"]
            assignment = lookup.get(slot_key)
            if not assignment:
                columns[day_index].markdown(
                    '<div class="empty-slot"></div>', unsafe_allow_html=True
                )
                continue
            name = assignment["name"]
            if clickable:
                if columns[day_index].button(
                    name,
                    key=f"{key_prefix}_{slot_key}_{assignment['client_id']}",
                    use_container_width=True,
                ):
                    st.session_state.selected_schedule_client_id = assignment[
                        "client_id"
                    ]
            else:
                columns[day_index].button(
                    name,
                    key=f"{key_prefix}_{slot_key}_{assignment['client_id']}",
                    use_container_width=True,
                    disabled=True,
                )


def render_selected_client_details() -> None:
    client_id = st.session_state.get("selected_schedule_client_id")
    if not client_id:
        return
    client = database.get_client(client_id, DB_PATH)
    if not client:
        st.session_state.pop("selected_schedule_client_id", None)
        return
    assignments = database.get_current_assignments(DB_PATH).get(client_id, [])

    st.divider()
    st.subheader(client["name"])
    left, right = st.columns([1.1, 1.9])
    with left:
        st.markdown("**Location**")
        st.write(client["location"] or "No location added")
        st.markdown("**Notes**")
        st.write(client["notes"] or "No notes added")
    with right:
        st.markdown("**Appointments and locks**")
        if not assignments:
            st.info("This client is waiting for a time.")
        for assignment in sorted(
            assignments,
            key=lambda item: (
                SLOT_BY_KEY[item["slot_key"]].day_index,
                SLOT_BY_KEY[item["slot_key"]].time_index,
            ),
        ):
            c1, c2 = st.columns([3, 1])
            c1.write(SLOT_KEY_TO_LABEL[assignment["slot_key"]])
            label = "Unlock" if assignment["locked"] else "Lock"
            if c2.button(label, key=f"lock_{assignment['id']}"):
                database.set_assignment_lock(
                    assignment["id"], not bool(assignment["locked"]), DB_PATH
                )
                st.rerun()
        st.caption(
            "A locked appointment stays at that exact time. Editing this same client can move it, and the new time will remain locked."
        )


def schedule_page() -> None:
    st.markdown('<div class="eyebrow">Approved weekly plan</div>', unsafe_allow_html=True)
    st.title("Schedule")
    preferred = database.get_preferred_evenings(DB_PATH)
    st.caption(
        f"The scheduler tries to keep **{preferred[0]}** and **{preferred[1]}** evenings free."
    )

    assignments = database.get_current_assignments(DB_PATH)
    if not assignments:
        st.info("No appointments are scheduled yet. Add the first client to begin.")
    render_schedule_grid(assignments, key_prefix="approved", clickable=True)
    render_selected_client_details()

    st.divider()
    st.subheader("Improve schedule")
    st.write(
        "This may move appointments to reduce gaps and keep more evenings free. "
        "Nothing changes until you review and approve the draft."
    )
    if st.button("Improve schedule", type="secondary"):
        try:
            show_result(service.request_improve_schedule(DB_PATH))
        except Exception as exc:
            st.error(str(exc))


def add_client_page() -> None:
    st.markdown('<div class="eyebrow">New recurring appointment</div>', unsafe_allow_html=True)
    st.title("Add Client")
    st.write("Enter the client information, then choose every time that can work.")

    c1, c2 = st.columns(2)
    name = c1.text_input("Client name", key="add_client_name")
    location = c2.text_input("Location", key="add_client_location")
    sessions = c1.number_input(
        "Sessions each week", min_value=1, max_value=5, value=1, step=1,
        key="add_client_sessions",
    )
    notes = st.text_area("Notes", height=90, key="add_client_notes")
    st.subheader("Weekly availability")
    availability = render_add_availability_grid()
    submitted = st.button("Save and find a time", type="primary")

    if submitted:
        try:
            result = service.add_client(
                name=name,
                location=location,
                notes=notes,
                sessions_per_week=int(sessions),
                availability=availability,
                db_path=DB_PATH,
            )
            show_result(result)
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"The client could not be saved: {exc}")


def client_edit_form(client: dict) -> None:
    client_id = int(client["id"])
    saved_availability = database.get_client_availability(client_id, DB_PATH)
    st.divider()
    st.subheader(f"Edit {client['name']}")
    st.caption("The approved client information stays unchanged until the draft is approved.")

    with st.form(f"edit_client_{client_id}"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Client name", value=client["name"])
        location = c2.text_input("Location", value=client["location"])
        sessions = c1.number_input(
            "Sessions each week",
            min_value=1,
            max_value=5,
            value=int(client["sessions_per_week"]),
            step=1,
        )
        notes = st.text_area("Notes", value=client["notes"], height=90)
        st.subheader("Weekly availability")
        availability = render_availability_editor(
            saved=saved_availability,
            key=f"edit_availability_{client_id}",
        )
        save = st.form_submit_button("Save changes to draft", type="primary")

    if save:
        try:
            show_result(
                service.edit_client(
                    client_id=client_id,
                    name=name,
                    location=location,
                    notes=notes,
                    sessions_per_week=int(sessions),
                    availability=availability,
                    db_path=DB_PATH,
                )
            )
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"The changes could not be saved: {exc}")


def clients_page() -> None:
    st.markdown('<div class="eyebrow">People and preferences</div>', unsafe_allow_html=True)
    st.title("Clients")
    clients = database.list_clients(DB_PATH)
    if not clients:
        st.info("No clients have been saved yet.")
        return

    names = {client["name"]: client for client in clients}
    selected_name = st.selectbox("Choose a client", list(names))
    client = names[selected_name]
    status_text = "Scheduled" if client["scheduled_sessions"] else "Waiting for a time"
    st.markdown(f'<span class="status-pill">{status_text}</span>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Sessions each week", int(client["sessions_per_week"]))
    c2.metric("Scheduled sessions", int(client["scheduled_sessions"]))
    c3.metric("Location", client["location"] or "—")
    st.markdown("**Notes**")
    st.write(client["notes"] or "No notes added")

    b1, b2 = st.columns(2)
    if b1.button("Edit client", type="primary", use_container_width=True):
        st.session_state.edit_client_id = int(client["id"])
    if b2.button("Delete client", use_container_width=True):
        st.session_state.delete_client_id = int(client["id"])

    if st.session_state.get("delete_client_id") == int(client["id"]):
        st.warning(
            f"Delete {client['name']}? This will permanently remove the client and all appointments when the draft is approved."
        )
        confirm = st.checkbox(
            "I understand that this client will be permanently deleted.",
            key=f"confirm_delete_{client['id']}",
        )
        d1, d2 = st.columns(2)
        if d1.button(
            "Add delete to draft",
            disabled=not confirm,
            type="primary",
            key=f"delete_yes_{client['id']}",
        ):
            try:
                show_result(
                    service.delete_client(client_id=int(client["id"]), db_path=DB_PATH)
                )
                st.session_state.pop("delete_client_id", None)
            except Exception as exc:
                st.error(str(exc))
        if d2.button("Cancel", key=f"delete_no_{client['id']}"):
            st.session_state.pop("delete_client_id", None)
            st.rerun()

    if st.session_state.get("edit_client_id") == int(client["id"]):
        client_edit_form(client)


def _effective_draft_names() -> dict[int, str]:
    names = {client["id"]: client["name"] for client in database.list_clients(DB_PATH)}
    for change in database.list_draft_changes(DB_PATH):
        if change["change_type"] in {"add", "edit"} and change["proposed_name"]:
            names[change["client_id"]] = change["proposed_name"]
    return names


def schedule_change_table() -> pd.DataFrame:
    approved = database.get_current_assignments(DB_PATH)
    draft = database.get_draft_assignments(DB_PATH)
    names = _effective_draft_names()
    client_ids = set(approved) | set(draft)
    rows: list[dict] = []
    for client_id in sorted(client_ids, key=lambda value: names.get(value, "").lower()):
        old = {item["slot_key"] for item in approved.get(client_id, [])}
        new = {item["slot_key"] for item in draft.get(client_id, [])}
        if old == new:
            continue
        rows.append(
            {
                "Client": names.get(client_id, "Client"),
                "Current": _format_slot_set(old) or "Not scheduled",
                "Draft": _format_slot_set(new) or "Removed",
            }
        )
    return pd.DataFrame(rows)


def _format_slot_set(slot_keys: set[str]) -> str:
    ordered = sorted(
        slot_keys,
        key=lambda key: (SLOT_BY_KEY[key].day_index, SLOT_BY_KEY[key].time_index),
    )
    return ", ".join(SLOT_KEY_TO_LABEL[key] for key in ordered)


def draft_page() -> None:
    st.markdown('<div class="eyebrow">Review before applying</div>', unsafe_allow_html=True)
    st.title("Draft Schedule")
    meta = database.get_draft_meta(DB_PATH)
    changes = database.list_draft_changes(DB_PATH)

    if not meta:
        st.info("There are no draft changes. The approved schedule is unchanged.")
        return

    st.success(meta["category"])
    st.write(meta["message"])
    st.caption(
        "All draft changes are approved together. You can remove one request or discard the entire draft first."
    )

    if changes:
        st.subheader("Requested changes")
        for change in changes:
            proposed_name = change.get("proposed_name") or change["current_name"]
            label = {
                "add": f"Add {proposed_name}",
                "edit": f"Edit {proposed_name}",
                "delete": f"Delete {change['current_name']}",
            }[change["change_type"]]
            c1, c2 = st.columns([5, 1])
            c1.write(label)
            if c2.button("Remove", key=f"remove_change_{change['id']}"):
                try:
                    show_result(service.remove_draft_change(change["id"], DB_PATH))
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    changes_frame = schedule_change_table()
    st.subheader("Appointment changes")
    if changes_frame.empty:
        st.info("No appointment times need to change.")
    else:
        st.dataframe(changes_frame, hide_index=True, use_container_width=True)

    approved_tab, draft_tab = st.tabs(["Approved schedule", "Draft schedule"])
    with approved_tab:
        render_schedule_grid(
            database.get_current_assignments(DB_PATH),
            key_prefix="draft_current",
            clickable=False,
        )
    with draft_tab:
        render_schedule_grid(
            database.get_draft_assignments(DB_PATH),
            key_prefix="draft_new",
            clickable=False,
        )

    st.divider()
    a1, a2 = st.columns(2)
    if a1.button("Approve entire draft", type="primary", use_container_width=True):
        try:
            show_result(service.approve_draft(DB_PATH))
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if a2.button("Discard entire draft", use_container_width=True):
        st.session_state.confirm_discard_draft = True

    if st.session_state.get("confirm_discard_draft"):
        st.warning("Discard every draft change? The approved schedule will stay exactly the same.")
        c1, c2 = st.columns(2)
        if c1.button("Yes, discard draft", type="primary"):
            show_result(service.discard_draft(DB_PATH))
            st.session_state.pop("confirm_discard_draft", None)
            st.rerun()
        if c2.button("Keep draft"):
            st.session_state.pop("confirm_discard_draft", None)
            st.rerun()


def settings_page() -> None:
    st.markdown('<div class="eyebrow">Scheduling preferences</div>', unsafe_allow_html=True)
    st.title("Settings")
    current_first, current_second = database.get_preferred_evenings(DB_PATH)
    st.write(
        "Choose the two evenings you most want to keep free. The scheduler protects these after avoiding unnecessary appointment moves."
    )

    c1, c2 = st.columns(2)
    first = c1.selectbox(
        "First preferred free evening",
        DAYS,
        index=DAYS.index(current_first),
    )
    second_options = [day for day in DAYS if day != first]
    second_default = current_second if current_second in second_options else second_options[0]
    second = c2.selectbox(
        "Second preferred free evening",
        second_options,
        index=second_options.index(second_default),
    )
    if st.button("Save settings", type="primary"):
        try:
            show_result(
                service.update_preferred_evenings(
                    first=first, second=second, db_path=DB_PATH
                )
            )
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.caption(f"Project build: {APP_BUILD}")


PAGES = ["Schedule", "Add Client", "Clients", "Draft Schedule", "Settings"]
if "page" not in st.session_state:
    st.session_state.page = "Schedule"

st.sidebar.markdown("## Weekly Scheduler")
st.sidebar.caption("One provider · 30-minute sessions")
page = st.sidebar.radio("Go to", PAGES, key="page")

if database.has_draft(DB_PATH):
    st.sidebar.info("A draft schedule is waiting for review.")

if page == "Schedule":
    schedule_page()
elif page == "Add Client":
    add_client_page()
elif page == "Clients":
    clients_page()
elif page == "Draft Schedule":
    draft_page()
else:
    settings_page()

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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

DB_PATH = database.DEFAULT_DB_PATH

st.set_page_config(
    page_title="Weekly Client Scheduler",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def check_database_connection() -> None:
    """Run the initial database connection check once per app process."""
    database.init_db(DB_PATH)


try:
    check_database_connection()
except Exception:
    st.error("The scheduler could not connect to Supabase.")
    st.info("Check that SUPABASE_DB_URL is present in this app's Streamlit Secrets.")
    st.stop()

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
    [data-testid="stHeader"], [data-testid="stToolbar"] { display: none; }
    .block-container { max-width: 1500px; padding-top: 1rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: var(--ink); letter-spacing: -0.02em; }
    [data-testid="stSidebar"] { background: #eaf1f7; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .25rem; }
    [data-testid="stSidebar"] label[data-baseweb="radio"] {
        width: 100%; padding: .55rem .7rem; border-radius: 9px;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child,
    [data-testid="stSidebar"] label[data-baseweb="radio"] > div:first-child {
        display: none !important;
    }
    [data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) {
        background: var(--blue); color: white; font-weight: 700;
    }
    [data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) p { color: white; }
    div[data-baseweb="tab-highlight"] { display: none; }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: var(--blue-soft); border-radius: 8px 8px 0 0; color: var(--blue-dark);
    }
    div[data-testid="stForm"], div[data-testid="stExpander"], .clean-card {
        background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
        padding: 1rem; box-shadow: 0 5px 18px rgba(48, 73, 97, .06);
    }
    .muted { color: var(--muted); }
    .schedule-day-heading { text-align: center; font-weight: 700; }
    .schedule-time { color: var(--muted); font-weight: 650; padding-top: .55rem; }
    .empty-slot { height: 2.65rem; border: 1px dashed #cfd9e2; border-radius: 9px;
        background: var(--gray-soft); }
    .section-gap { height: .75rem; }
    .status-pill { display: inline-block; padding: .28rem .62rem; border-radius: 999px;
        background: var(--blue-soft); color: var(--blue-dark); font-size: .82rem; font-weight: 700; }
    .client-detail-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem; margin-top: 1rem; }
    .client-detail-card { min-width: 0; background: var(--panel); border: 1px solid var(--line);
        border-radius: 12px; padding: .9rem 1rem;
        box-shadow: 0 4px 12px rgba(48, 73, 97, .08); }
    .client-detail-label { color: var(--muted); font-size: .82rem; font-weight: 650;
        margin-bottom: .35rem; }
    .client-detail-value { color: var(--ink); font-size: 1rem; white-space: pre-wrap;
        overflow-wrap: anywhere; }
    @media (max-width: 700px) {
        .client-detail-grid { grid-template-columns: 1fr; }
    }
    div.stButton > button { border-radius: 9px; border: 1px solid #cddae6; }
    div.stButton > button[kind="primary"] { background: var(--blue-dark); border-color: var(--blue-dark); }
    .st-key-schedule_grid div.stButton > button {
        height: 2.65rem; min-height: 2.65rem; background: var(--panel);
        border-color: #b9cbd9; color: var(--ink); font-weight: 650;
        box-shadow: 0 2px 5px rgba(48, 73, 97, .1);
    }
    div[class*="st-key-schedule_row_"] { min-height: 2.65rem; margin-bottom: .35rem; }
    div[class*="st-key-schedule_row_"] div[data-testid="stHorizontalBlock"] {
        min-height: 2.65rem; align-items: center;
    }
    div[class*="st-key-schedule_row_"] div.stButton { height: 2.65rem; margin: 0; }
    div[class*="st-key-schedule_row_"] div.stButton > button,
    div[class*="st-key-schedule_row_"] .empty-slot {
        height: 2.65rem; min-height: 2.65rem; margin: 0;
    }
    div[class*="st-key-draft_current_"] button:disabled {
        background: var(--panel); border-color: #b9cbd9; color: var(--ink);
        box-shadow: 0 2px 5px rgba(48, 73, 97, .1); opacity: 1;
    }
    .st-key-client_actions, .st-key-client_delete_section, .st-key-client_edit_section {
        width: 100%; max-width: 48rem; margin-inline: auto;
    }
    .st-key-draft_actions, .st-key-draft_discard_section {
        width: 100%; max-width: 38rem; margin-inline: auto;
    }
    .st-key-discard_entire_draft button,
    .st-key-confirm_discard_entire_draft button {
        background: var(--danger); border-color: var(--danger); color: white;
    }
    .st-key-draft_proposed div.stButton > button:disabled {
        background: var(--panel); border-color: #b9cbd9; color: var(--ink);
        box-shadow: 0 2px 5px rgba(48, 73, 97, .1); opacity: 1;
    }
    .st-key-draft_proposed div[class*="st-key-changed_schedule_slot_"] button:disabled {
        background: var(--blue-soft); border-color: #cbddeb; color: var(--blue-dark);
    }
    div[data-baseweb="input"], div[data-baseweb="base-input"],
    div[data-baseweb="textarea"], div[data-baseweb="select"] > div {
        background-color: var(--panel);
    }
    div[data-baseweb="input"], div[data-baseweb="textarea"],
    div[data-baseweb="select"] > div {
        border-color: #b9cbd9; box-shadow: 0 1px 3px rgba(48, 73, 97, .08);
    }
    div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea {
        background-color: transparent;
    }
    div[data-testid="stDataEditor"] { background: white; border-radius: 12px; overflow: hidden; }
    .draft-note { background: #eef5fa; border-left: 4px solid var(--blue); padding: .8rem 1rem;
        border-radius: 8px; color: var(--ink); }
    .availability-day { text-align: center; font-weight: 700; padding: .45rem 0 .55rem; }
    .availability-intro { display: flex; align-items: baseline; flex-wrap: wrap;
        gap: .35rem .75rem; margin: .8rem 0 .25rem; }
    .availability-intro-title { color: var(--ink); font-size: .95rem; font-weight: 700; }
    .availability-intro-note { color: var(--muted); font-size: .82rem; }
    .availability-legend { display: flex; flex-wrap: wrap; gap: .45rem 1rem;
        margin: .25rem 0 .7rem; color: var(--muted); font-size: .82rem; }
    .availability-legend span { display: inline-flex; align-items: center; gap: .35rem; }
    .availability-swatch { width: .8rem; height: .8rem; border-radius: 4px;
        display: inline-block; border: 1px solid #c7d5e1; }
    .availability-swatch.best { background: var(--blue-dark); border-color: var(--blue-dark); }
    .availability-swatch.works { background: var(--blue-soft); border-color: #b5cde0; }
    .availability-swatch.unavailable { background: var(--panel); border-style: dashed; }
    .st-key-add_availability_grid div.stButton > button { min-height: 2.65rem; }
    .st-key-add_availability_grid div.stButton > button[kind="primary"] {
        background: var(--blue-dark); border-color: var(--blue-dark); color: white;
    }
    .st-key-add_availability_grid div.stButton > button[kind="secondary"] {
        background: var(--blue-soft); border-color: #b5cde0; color: var(--blue-dark);
    }
    .st-key-add_availability_grid div.stButton > button[kind="tertiary"] {
        background: var(--panel); border: 1px dashed #c7d5e1; color: var(--muted);
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
            st.info("Review everything on the **Review Changes** page before approving it.")
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


def split_client_name(name: str) -> tuple[str, str]:
    parts = name.strip().split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def combine_client_name(first_name: str, last_name: str) -> str:
    return " ".join(part.strip() for part in (first_name, last_name) if part.strip())


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

    st.markdown(
        """
        <div class="availability-legend" aria-label="Availability colors">
            <span><i class="availability-swatch best"></i>Best time</span>
            <span><i class="availability-swatch works"></i>Also works</span>
            <span><i class="availability-swatch unavailable"></i>Not available</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    values = st.session_state[state_key]
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
                columns[day_index].button(
                    PREFERENCE_LABELS[preference],
                    key=f"add_slot_{slot_key}",
                    type=button_types[preference],
                    use_container_width=True,
                    on_click=cycle_add_availability,
                    args=(slot_key,),
                )

    return {
        slot_key: preference
        for slot_key, preference in values.items()
        if preference != PREFERENCE_UNAVAILABLE
    }


def cycle_add_availability(slot_key: str) -> None:
    """Advance one Add Client availability button before Streamlit reruns."""
    values = st.session_state["add_availability_values"]
    cycle = {
        PREFERENCE_UNAVAILABLE: "optimal",
        "optimal": "secondary",
        "secondary": PREFERENCE_UNAVAILABLE,
    }
    values[slot_key] = cycle[values[slot_key]]


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
    highlighted_slots: set[str] | None = None,
) -> None:
    lookup = assignment_lookup(assignments)
    header = st.columns([1.05, 1, 1, 1, 1, 1])
    header[0].markdown("**Time**")
    for index, day in enumerate(DAYS, start=1):
        header[index].markdown(
            f'<div class="schedule-day-heading">{day}</div>', unsafe_allow_html=True
        )

    for time_index, time_label in enumerate(TIMES):
        if time_label == EVENING_TIMES[0]:
            st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
            st.caption("Evening")
        with st.container(key=f"schedule_row_{key_prefix}_{time_index}"):
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
                button_key = f"{key_prefix}_{slot_key}_{assignment['client_id']}"
                if highlighted_slots and slot_key in highlighted_slots:
                    button_key = (
                        f"changed_schedule_slot_{key_prefix}_{slot_key}_"
                        f"{assignment['client_id']}"
                    )
                if clickable:
                    if columns[day_index].button(
                        name,
                        key=button_key,
                        use_container_width=True,
                    ):
                        st.session_state.selected_schedule_client_id = assignment[
                            "client_id"
                        ]
                else:
                    columns[day_index].button(
                        name,
                        key=button_key,
                        use_container_width=True,
                        disabled=True,
                    )


def clear_selected_schedule_client() -> None:
    st.session_state.pop("selected_schedule_client_id", None)
    st.session_state.pop("schedule_lock_confirmation", None)


@st.dialog(
    "Client details", width="medium", on_dismiss=clear_selected_schedule_client
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

    st.subheader(client["name"])
    st.markdown(f"**Location:** {client['location'] or 'No location added'}")
    st.markdown(f"**Notes:** {client['notes'] or 'No notes added'}")
    if not assignments:
        st.info("This client is waiting for a time.")
    for assignment in sorted(
        assignments,
        key=lambda item: (
            SLOT_BY_KEY[item["slot_key"]].day_index,
            SLOT_BY_KEY[item["slot_key"]].time_index,
        ),
    ):
        st.markdown(f"**Appointments:** {SLOT_KEY_TO_LABEL[assignment['slot_key']]}")
        label = "Unlock" if assignment["locked"] else "Lock"
        if st.button(label, key=f"lock_{assignment['id']}"):
            database.set_assignment_lock(
                assignment["id"], not bool(assignment["locked"]), DB_PATH
            )
            completed_action = "unlocked" if assignment["locked"] else "locked"
            st.session_state.schedule_lock_confirmation = (
                f"Appointment {completed_action}."
            )
            st.rerun()
    confirmation = st.session_state.pop("schedule_lock_confirmation", None)
    if confirmation:
        st.success(confirmation)


def schedule_page() -> None:
    heading, action = st.columns([3, 1.35], vertical_alignment="top")
    heading.title("Schedule")
    improve = action.button(
        "Improve schedule", type="secondary", use_container_width=True
    )
    action.caption(
        "May move appointments to reduce gaps. You’ll review changes before they apply."
    )
    if improve:
        try:
            show_result(service.request_improve_schedule(DB_PATH))
        except Exception as exc:
            st.error(str(exc))

    preferred = database.get_preferred_evenings(DB_PATH)
    st.caption(
        f"The scheduler tries to keep **{preferred[0]}** and **{preferred[1]}** evenings free."
    )

    assignments = database.get_current_assignments(DB_PATH)
    if not assignments:
        st.info("No appointments are scheduled yet. Add the first client to begin.")
    with st.container(key="schedule_grid"):
        render_schedule_grid(assignments, key_prefix="approved", clickable=True)
    if st.session_state.get("selected_schedule_client_id"):
        render_selected_client_details()


def add_client_page() -> None:
    st.title("Add Client")
    st.write("Enter the client information, then choose every time that can work.")

    c1, c2, c3 = st.columns(3)
    first_name = c1.text_input("First name", key="add_client_first_name")
    last_name = c2.text_input("Last name", key="add_client_last_name")
    location = c3.text_input("Location", key="add_client_location")
    sessions = st.number_input(
        "Sessions each week", min_value=1, max_value=5, value=1, step=1,
        key="add_client_sessions",
    )
    notes = st.text_area("Notes", height=90, key="add_client_notes")
    st.markdown(
        """
        <div class="availability-intro">
            <span class="availability-intro-title">Weekly availability</span>
            <span class="availability-intro-note">Click a box to cycle through
                <strong>Not available</strong>, <strong>Best time</strong>, and
                <strong>Also works</strong>.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    availability = render_add_availability_grid()
    submitted = st.button("Save client and find a time", type="primary")

    if submitted:
        try:
            result = service.add_client(
                name=combine_client_name(first_name, last_name),
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
    first_name, last_name = split_client_name(client["name"])
    saved_availability = database.get_client_availability(client_id, DB_PATH)
    st.divider()
    st.subheader(f"Edit {client['name']}")
    st.caption("The approved client information stays unchanged until the draft is approved.")

    with st.form(f"edit_client_{client_id}"):
        c1, c2, c3 = st.columns(3)
        first_name = c1.text_input("First name", value=first_name)
        last_name = c2.text_input("Last name", value=last_name)
        location = c3.text_input("Location", value=client["location"])
        sessions = st.number_input(
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
                    name=combine_client_name(first_name, last_name),
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

    st.markdown(
        f"""
        <div class="client-detail-grid">
            <div class="client-detail-card">
                <div class="client-detail-label">Sessions per week</div>
                <div class="client-detail-value">{int(client['sessions_per_week'])}</div>
            </div>
            <div class="client-detail-card">
                <div class="client-detail-label">Location</div>
                <div class="client-detail-value">{escape(client['location'] or 'No location added')}</div>
            </div>
            <div class="client-detail-card">
                <div class="client-detail-label">Notes</div>
                <div class="client-detail-value">{escape(client['notes'] or 'No notes added')}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    with st.container(key="client_actions"):
        b1, b2 = st.columns(2)
        if b1.button("Edit client", type="primary", use_container_width=True):
            st.session_state.edit_client_id = int(client["id"])
        if b2.button("Delete client", use_container_width=True):
            st.session_state.delete_client_id = int(client["id"])

    if st.session_state.get("delete_client_id") == int(client["id"]):
        with st.container(key="client_delete_section"):
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
                        service.delete_client(
                            client_id=int(client["id"]), db_path=DB_PATH
                        )
                    )
                    st.session_state.pop("delete_client_id", None)
                except Exception as exc:
                    st.error(str(exc))
            if d2.button("Cancel", key=f"delete_no_{client['id']}"):
                st.session_state.pop("delete_client_id", None)
                st.rerun()

    if st.session_state.get("edit_client_id") == int(client["id"]):
        with st.container(key="client_edit_section"):
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
                "Now": _format_slot_set(old) or "Not scheduled",
                "After approval": _format_slot_set(new) or "Removed",
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
    st.title("Review Changes")
    meta = database.get_draft_meta(DB_PATH)

    if not meta:
        st.info("There are no draft changes. The approved schedule is unchanged.")
        return

    draft_assignments = database.get_draft_assignments(DB_PATH)
    current_assignments = database.get_current_assignments(DB_PATH)
    current_by_slot = assignment_lookup(current_assignments)
    changed_proposed_slots = {
        slot_key
        for slot_key, assignment in assignment_lookup(draft_assignments).items()
        if current_by_slot.get(slot_key, {}).get("client_id")
        != assignment["client_id"]
    }
    with st.container(key="draft_actions"):
        a1, a2 = st.columns(2)
        if a1.button("Approve", type="primary", use_container_width=True):
            try:
                show_result(service.approve_draft(DB_PATH))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if a2.button(
            "Discard",
            key="discard_entire_draft",
            use_container_width=True,
        ):
            st.session_state.confirm_discard_draft = True

    if st.session_state.get("confirm_discard_draft"):
        with st.container(key="draft_discard_section"):
            st.warning(
                "Discard every draft change? The approved schedule will stay exactly the same."
            )
            c1, c2 = st.columns(2)
            if c1.button(
                "Yes, discard draft", key="confirm_discard_entire_draft"
            ):
                show_result(service.discard_draft(DB_PATH))
                st.session_state.pop("confirm_discard_draft", None)
                st.rerun()
            if c2.button("Keep draft"):
                st.session_state.pop("confirm_discard_draft", None)
                st.rerun()

    changes_frame = schedule_change_table()
    st.subheader("What will change")
    if changes_frame.empty:
        st.info("No appointment times need to change.")
    else:
        styled_changes = changes_frame.style.set_properties(
            subset=["After approval"], background_color="#e8f1f8"
        )
        st.dataframe(styled_changes, hide_index=True, use_container_width=True)

    approved_tab, draft_tab = st.tabs(
        ["Current", "New schedule"], default="New schedule"
    )
    with approved_tab:
        render_schedule_grid(
            current_assignments,
            key_prefix="draft_current",
            clickable=False,
        )
    with draft_tab:
        with st.container(key="draft_proposed"):
            render_schedule_grid(
                draft_assignments,
                key_prefix="draft_new",
                clickable=False,
                highlighted_slots=changed_proposed_slots,
            )


def settings_page() -> None:
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
    st.subheader("Appointment locks")
    st.write(
        "A locked appointment stays at that exact time. Editing this same client can move it, and the new time will remain locked."
    )


def reset_page_scroll() -> None:
    st.session_state.scroll_to_page_top = True


PAGES = ["Schedule", "Add Client", "Clients", "Review Changes", "Settings"]
if st.session_state.get("page") == "Draft Schedule":
    st.session_state.page = "Review Changes"
elif "page" not in st.session_state:
    st.session_state.page = "Schedule"

st.sidebar.markdown("## Weekly Scheduler")
page = st.sidebar.radio(
    "Pages",
    PAGES,
    key="page",
    label_visibility="collapsed",
    on_change=reset_page_scroll,
)

if st.session_state.pop("scroll_to_page_top", False):
    components.html(
        """
        <script>
        const app = window.parent.document.querySelector('[data-testid="stAppViewContainer"]');
        if (app) app.scrollTo(0, 0);
        window.parent.scrollTo(0, 0);
        </script>
        """,
        height=0,
        width=0,
    )

if page == "Schedule":
    schedule_page()
elif page == "Add Client":
    add_client_page()
elif page == "Clients":
    clients_page()
elif page == "Review Changes":
    draft_page()
else:
    settings_page()

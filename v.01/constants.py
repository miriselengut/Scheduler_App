from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]
DAY_CODES = {
    "Sunday": "SUN",
    "Monday": "MON",
    "Tuesday": "TUE",
    "Wednesday": "WED",
    "Thursday": "THU",
}

AFTERNOON_TIMES = [
    "2:00 PM", "2:30 PM", "3:00 PM", "3:30 PM",
    "4:00 PM", "4:30 PM", "5:00 PM", "5:30 PM",
]
EVENING_TIMES = [
    "8:00 PM", "8:30 PM", "9:00 PM", "9:30 PM",
    "10:00 PM", "10:30 PM",
]
TIMES = AFTERNOON_TIMES + EVENING_TIMES

PREFERENCE_OPTIMAL = "optimal"
PREFERENCE_SECONDARY = "secondary"
PREFERENCE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Slot:
    key: str
    day: str
    time: str
    day_index: int
    time_index: int
    block: str
    block_index: int

    @property
    def label(self) -> str:
        return f"{self.day} {self.time}"


def _time_code(time_label: str) -> str:
    return datetime.strptime(time_label, "%I:%M %p").strftime("%H%M")


def build_slots() -> list[Slot]:
    slots: list[Slot] = []
    for day_index, day in enumerate(DAYS):
        for time_index, time_label in enumerate(TIMES):
            is_afternoon = time_label in AFTERNOON_TIMES
            block = "afternoon" if is_afternoon else "evening"
            block_index = (
                AFTERNOON_TIMES.index(time_label)
                if is_afternoon
                else EVENING_TIMES.index(time_label)
            )
            slots.append(
                Slot(
                    key=f"{DAY_CODES[day]}_{_time_code(time_label)}",
                    day=day,
                    time=time_label,
                    day_index=day_index,
                    time_index=time_index,
                    block=block,
                    block_index=block_index,
                )
            )
    return slots


SLOTS = build_slots()
SLOT_BY_KEY = {slot.key: slot for slot in SLOTS}
SLOT_KEYS = [slot.key for slot in SLOTS]
SLOT_LABEL_TO_KEY = {slot.label: slot.key for slot in SLOTS}
SLOT_KEY_TO_LABEL = {slot.key: slot.label for slot in SLOTS}

"""Local calendar and opt-in advance reminders for KaptiaLab.

Reminder delivery is local-only. The scheduler is polled by the desktop workspace;
it never sends calendar data to a remote service.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    title: str
    event_date: str
    event_time: str
    notes: str
    reminder_days: tuple[int, ...] = (1,)


class CalendarStore:
    """Atomic JSON-backed event store scoped to the current Windows user."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                value.setdefault("settings", {})
                value.setdefault("events", [])
                value.setdefault("sent_reminders", [])
                return value
        except (OSError, json.JSONDecodeError):
            pass
        return {"settings": {"reminders_enabled": False}, "events": [], "sent_reminders": []}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def reminders_enabled(self) -> bool:
        with self._lock:
            return bool(self._read()["settings"].get("reminders_enabled", False))

    def set_reminders_enabled(self, enabled: bool) -> None:
        with self._lock:
            data = self._read()
            data["settings"]["reminders_enabled"] = bool(enabled)
            self._write(data)

    def list_events(self) -> list[CalendarEvent]:
        with self._lock:
            result = []
            for raw in self._read()["events"]:
                try:
                    result.append(CalendarEvent(
                        event_id=str(raw["event_id"]), title=str(raw["title"]),
                        event_date=str(raw["event_date"]), event_time=str(raw.get("event_time", "09:00")),
                        notes=str(raw.get("notes", "")),
                        reminder_days=tuple(sorted({int(x) for x in raw.get("reminder_days", [1]) if int(x) in (1, 2)}, reverse=True)),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
            return sorted(result, key=lambda e: (e.event_date, e.event_time, e.title.casefold()))

    def add_event(self, title: str, event_date: str, event_time: str = "09:00",
                  notes: str = "", reminder_days: tuple[int, ...] = (1,)) -> CalendarEvent:
        title = title.strip()
        if not title:
            raise ValueError("行程標題不可為空。")
        parsed_date = date.fromisoformat(event_date)
        parsed_time = time.fromisoformat(event_time)
        days = tuple(sorted({int(x) for x in reminder_days}, reverse=True))
        if not days or any(x not in (1, 2) for x in days):
            raise ValueError("提醒時間只能選擇提前 1 天或 2 天，至少選一項。")
        event = CalendarEvent(uuid.uuid4().hex, title, parsed_date.isoformat(),
                              parsed_time.strftime("%H:%M"), notes.strip(), days)
        with self._lock:
            data = self._read()
            data["events"].append(asdict(event))
            self._write(data)
        return event

    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            data = self._read()
            before = len(data["events"])
            data["events"] = [e for e in data["events"] if e.get("event_id") != event_id]
            self._write(data)
            return len(data["events"]) != before

    def due_reminders(self, now: datetime | None = None) -> list[dict[str, str]]:
        """Return and atomically claim due reminders; each lead-time fires once.

        Delivery time is 09:00 in the machine's local timezone on the selected
        reminder date. A reminder is not delivered after its event has started.
        """
        now = now or datetime.now().astimezone()
        local_now = now.astimezone()
        due: list[dict[str, str]] = []
        with self._lock:
            data = self._read()
            if not data["settings"].get("reminders_enabled", False):
                return []
            sent = set(data.get("sent_reminders", []))
            for raw in data["events"]:
                try:
                    event_day = date.fromisoformat(raw["event_date"])
                    event_time = time.fromisoformat(raw.get("event_time", "09:00"))
                    event_dt = datetime.combine(event_day, event_time).astimezone()
                    if event_dt <= local_now:
                        continue
                    for lead in raw.get("reminder_days", [1]):
                        lead = int(lead)
                        if lead not in (1, 2):
                            continue
                        reminder_day = event_day - timedelta(days=lead)
                        reminder_at = datetime.combine(reminder_day, time(9, 0)).astimezone()
                        key = f'{raw["event_id"]}:{lead}:{event_day.isoformat()}'
                        if reminder_at <= local_now and key not in sent:
                            due.append({
                                "key": key, "event_id": str(raw["event_id"]),
                                "title": str(raw.get("title", "未命名行程")),
                                "event_date": event_day.isoformat(),
                                "event_time": event_time.strftime("%H:%M"),
                                "notes": str(raw.get("notes", "")),
                                "days_left": str(lead),
                            })
                            sent.add(key)
                except (KeyError, TypeError, ValueError):
                    continue
            if due:
                data["sent_reminders"] = sorted(sent)
                self._write(data)
        return due


def default_calendar_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kaptia"
    return root / "calendar.json"

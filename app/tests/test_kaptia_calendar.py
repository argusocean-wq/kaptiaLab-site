"""Tests for Kaptia's local calendar and opt-in reminder engine."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.kaptia_calendar import CalendarStore


class CalendarStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CalendarStore(Path(self.temp.name) / "calendar.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_reminders_are_disabled_by_default(self):
        self.store.add_event("專題報告", "2030-05-10", "10:30", "帶資料", (1, 2))
        self.assertFalse(self.store.reminders_enabled())
        self.assertEqual(self.store.due_reminders(datetime(2030, 5, 8, 10, tzinfo=timezone.utc)), [])

    def test_two_day_reminder_is_due_at_nine_local_time_and_only_once(self):
        self.store.add_event("專題報告", "2030-05-10", "10:30", "帶資料", (2,))
        self.store.set_reminders_enabled(True)
        now = datetime(2030, 5, 8, 10, tzinfo=timezone.utc)
        first = self.store.due_reminders(now)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["days_left"], "2")
        self.assertIn("帶資料", first[0]["notes"])
        self.assertEqual(self.store.due_reminders(now), [])

    def test_one_and_two_day_reminders_are_independent(self):
        self.store.add_event("面談", "2030-05-10", "14:00", "", (1, 2))
        self.store.set_reminders_enabled(True)
        two_days = self.store.due_reminders(datetime(2030, 5, 8, 10, tzinfo=timezone.utc))
        one_day = self.store.due_reminders(datetime(2030, 5, 9, 10, tzinfo=timezone.utc))
        self.assertEqual([x["days_left"] for x in two_days], ["2"])
        self.assertEqual([x["days_left"] for x in one_day], ["1"])

    def test_disabled_setting_suppresses_delivery_but_keeps_event(self):
        event = self.store.add_event("考試", "2030-05-10", reminder_days=(1,))
        self.store.set_reminders_enabled(True)
        self.store.set_reminders_enabled(False)
        self.assertEqual(self.store.due_reminders(datetime(2030, 5, 9, 10, tzinfo=timezone.utc)), [])
        self.assertEqual(len(self.store.list_events()), 1)
        self.assertEqual(self.store.list_events()[0].event_id, event.event_id)

    def test_invalid_event_and_reminder_selection_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_event("", "2030-05-10")
        with self.assertRaises(ValueError):
            self.store.add_event("測試", "not-a-date")
        with self.assertRaises(ValueError):
            self.store.add_event("測試", "2030-05-10", reminder_days=(3,))

    def test_delete_event(self):
        event = self.store.add_event("活動", "2030-05-10")
        self.assertTrue(self.store.delete_event(event.event_id))
        self.assertFalse(self.store.delete_event(event.event_id))
        self.assertEqual(self.store.list_events(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

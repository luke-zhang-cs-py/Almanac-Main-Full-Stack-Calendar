"""The imported timetable, and the reminder the planner cannot send itself.

The planner is one HTML file opened from disk. It can raise a notification
while its tab is open and nothing at all once it is closed, because a
file:// origin cannot register a service worker. So the planner exports, this
imports, and Almanac's sweep emails -- which works with nothing open.

Four things are guarded here, and only the first is ordinary CRUD:

  * **Re-importing does not duplicate.** The planner's term ids are
    deterministic, so the same export imported twice must update forty rows
    rather than add forty more. A timetable you cannot safely re-import is a
    timetable that goes stale.

  * **A moved class is reminded about again.** Updating a row clears its
    reminded mark, because a class that has moved is a different moment.

  * **Rows on another clock are never reminded about.** The planner stores a
    time as written with a timezone label; for anything not on the local
    clock the stored time is not the local instant, and a reminder then
    would be hours wrong.

  * **One email per class.** The de-duplication in email_log is declared
    WHERE appointment_id IS NOT NULL and so does nothing for these, which is
    exactly why the mark lives on the row. Without it every scan across the
    window would send again -- four times, at the default cadence.
"""

import datetime as dt

import pytest

from domain import schedule


def export(events):
    """What the planner's Export backup button writes."""
    return {"app": "september-planner", "version": 1,
            "exportedAt": "2026-09-13T12:00:00.000Z",
            "events": events, "dayTodos": {}, "todos": []}


def a_class(id="term-1", time="10:00", end="11:00", title="MAT 1001 · Lecture",
            **over):
    row = {"id": id, "time": time, "end": end, "title": title,
           "type": "class", "done": False}
    row.update(over)
    return row


def in_minutes(minutes):
    """A date and time that many minutes from now, planner-shaped."""
    at = dt.datetime.now() + dt.timedelta(minutes=minutes)
    return at.strftime("%Y-%m-%d"), at.strftime("%H:%M")


def sent(kind=None):
    from core import database as db
    if kind:
        return db.query("SELECT * FROM email_log WHERE kind = ? ORDER BY id",
                        (kind,))
    return db.query("SELECT * FROM email_log ORDER BY id")


# ------------------------------------------------------------- importing


def test_importing_a_planner_export(client, booking):
    body = client.post("/api/schedule/import", headers=booking["auth"],
                       json=export({"2026-09-21": [a_class()]})).get_json()
    assert body["imported"] == {"added": 1, "updated": 0, "skipped": 0}
    assert body["events"][0]["title"] == "MAT 1001 · Lecture"
    assert body["events"][0]["localClock"] is True


def test_reimporting_updates_rather_than_duplicates(client, booking):
    """The planner's term ids are deterministic, so the same export imported
    twice is the same forty classes -- not eighty."""
    payload = export({"2026-09-21": [a_class(), a_class(id="term-2",
                                                        time="14:00")]})
    first = client.post("/api/schedule/import", headers=booking["auth"],
                        json=payload).get_json()["imported"]
    second = client.post("/api/schedule/import", headers=booking["auth"],
                         json=payload).get_json()["imported"]
    assert first == {"added": 2, "updated": 0, "skipped": 0}
    assert second == {"added": 0, "updated": 2, "skipped": 0}

    listed = client.get("/api/schedule", headers=booking["auth"]).get_json()
    assert listed["count"] == 2


def test_a_moved_class_moves_rather_than_doubling(client, booking):
    client.post("/api/schedule/import", headers=booking["auth"],
                json=export({"2026-09-21": [a_class(time="10:00")]}))
    client.post("/api/schedule/import", headers=booking["auth"],
                json=export({"2026-09-28": [a_class(time="16:00")]}))

    listed = client.get("/api/schedule", headers=booking["auth"]).get_json()
    assert listed["count"] == 1
    assert listed["events"][0]["eventDate"] == "2026-09-28"
    assert listed["events"][0]["startTime"] == "16:00"


def test_rows_it_cannot_read_are_counted_not_dropped_silently(client, booking):
    """A half-read file should say so, or the timetable looks complete."""
    body = client.post("/api/schedule/import", headers=booking["auth"], json=export({
        "2026-09-21": [a_class(),
                       a_class(id="no-time", time=""),
                       a_class(id="no-title", title="")],
        "not-a-date": [a_class(id="bad-date")],
    })).get_json()
    assert body["imported"]["added"] == 1
    assert body["imported"]["skipped"] == 3


def test_a_day_holding_something_that_is_not_an_event(client, booking):
    """A hand-edited or truncated backup can have anything in the array.
    Counting it beats a 500, and beats pretending the file was fine."""
    body = client.post("/api/schedule/import", headers=booking["auth"],
                       json=export({"2026-09-21": [a_class(), "not a row", 7],
                                    "2026-09-22": "not a list"})).get_json()
    assert body["imported"]["added"] == 1
    assert body["imported"]["skipped"] == 3


@pytest.mark.parametrize("payload", [
    None, {}, {"app": "something-else", "events": {}},
    {"app": "september-planner"},
    {"app": "september-planner", "events": []},
])
def test_anything_that_is_not_a_planner_export_is_refused(client, booking,
                                                          payload):
    got = client.post("/api/schedule/import", headers=booking["auth"],
                      json=payload)
    assert got.status_code == 400, payload
    assert "planner" in got.get_json()["error"].lower() or \
           "events" in got.get_json()["error"].lower()


def test_a_class_on_another_clock_is_imported_but_flagged(client, booking):
    """"11:30 EST" is not the local instant. It is kept and shown, because
    it is still on your timetable -- it is only reminders it is excluded
    from."""
    body = client.post("/api/schedule/import", headers=booking["auth"],
                       json=export({"2026-09-21": [
                           a_class(id="far", tz="EST")]})).get_json()
    assert body["imported"]["added"] == 1
    assert body["events"][0]["localClock"] is False


def test_the_uk_clock_change_decides_the_label(ctx):
    """BST ran to 25 October 2026 and resumes 28 March 2027, so the same
    label is local on one side of that and not the other."""
    assert schedule.is_local_clock("2026-09-21", "BST") is True
    assert schedule.is_local_clock("2026-09-21", "GMT") is False
    assert schedule.is_local_clock("2026-12-02", "GMT") is True
    assert schedule.is_local_clock("2026-12-02", "BST") is False
    assert schedule.is_local_clock("2026-09-21", None) is True


# --------------------------------------------------------------- the list


def test_one_timetable_per_account(client, booking, provider):
    client.post("/api/schedule/import", headers=booking["auth"],
                json=export({"2026-09-21": [a_class()]}))
    theirs = client.get("/api/schedule", headers=provider["auth"]).get_json()
    assert theirs["events"] == []
    assert theirs["count"] == 0


def test_deleting_only_your_own(client, booking, provider):
    made = client.post("/api/schedule/import", headers=booking["auth"],
                       json=export({"2026-09-21": [a_class()]})).get_json()
    event_id = made["events"][0]["id"]

    assert client.delete(f"/api/schedule/{event_id}",
                         headers=provider["auth"]).status_code == 404
    assert client.delete(f"/api/schedule/{event_id}",
                         headers=booking["auth"]).status_code == 200


def test_clearing_starts_again(client, booking):
    client.post("/api/schedule/import", headers=booking["auth"],
                json=export({"2026-09-21": [a_class(), a_class(id="t2")]}))
    got = client.delete("/api/schedule", headers=booking["auth"]).get_json()
    assert got["deleted"] == 2
    assert client.get("/api/schedule",
                      headers=booking["auth"]).get_json()["count"] == 0


def test_the_whole_timetable_needs_a_token(client):
    for call in (client.get("/api/schedule"),
                 client.post("/api/schedule/import", json={}),
                 client.delete("/api/schedule"),
                 client.delete("/api/schedule/1")):
        assert call.status_code in (401, 403)


# ----------------------------------------------------------- the reminder


def import_one(client, booking, minutes, **over):
    date, time = in_minutes(minutes)
    client.post("/api/schedule/import", headers=booking["auth"],
                json=export({date: [a_class(time=time, end=None, **over)]}))
    return date, time


def test_a_class_inside_the_window_is_emailed(client, booking, ctx):
    from notify import notifications
    import_one(client, booking, 20)
    assert notifications.send_schedule_reminders() == 1
    rows = sent("schedule_soon")
    assert len(rows) == 1
    assert "MAT 1001" in rows[0]["subject"]


def test_a_class_beyond_the_window_is_not(client, booking, ctx):
    from notify import notifications
    import_one(client, booking, 90)
    assert notifications.send_schedule_reminders() == 0
    assert sent("schedule_soon") == []


def test_a_class_already_under_way_is_not_chased(client, booking, ctx):
    from notify import notifications
    import_one(client, booking, -10)
    assert notifications.send_schedule_reminders() == 0


def test_a_class_on_another_clock_is_never_emailed(client, booking, ctx):
    """The stored time is not the local instant, so there is no moment this
    could be sent at that would be right."""
    from notify import notifications
    import_one(client, booking, 20, id="far", tz="EST")
    assert notifications.send_schedule_reminders() == 0
    assert sent("schedule_soon") == []


def test_one_email_per_class_however_often_it_scans(client, booking, ctx):
    """email_log's unique index is declared WHERE appointment_id IS NOT NULL
    and so de-duplicates nothing here. Without the mark on the row, the
    default cadence would send this four times."""
    from notify import notifications
    import_one(client, booking, 25)
    assert notifications.send_schedule_reminders() == 1
    for _ in range(3):
        assert notifications.send_schedule_reminders() == 0
    assert len(sent("schedule_soon")) == 1


def test_a_moved_class_is_reminded_about_again(client, booking, ctx):
    """The mark is cleared on update, because a class that has moved is a
    different moment and the first reminder was about the old one."""
    from notify import notifications
    import_one(client, booking, 25)
    assert notifications.send_schedule_reminders() == 1

    # Rescheduled to a different time, still inside the window.
    import_one(client, booking, 15)
    assert notifications.send_schedule_reminders() == 1
    assert len(sent("schedule_soon")) == 2


def test_the_reminder_can_be_turned_off(client, booking, ctx):
    from notify import notifications
    from flask import current_app
    import_one(client, booking, 20)
    current_app.config["IMMINENT_ENABLED"] = False
    try:
        assert notifications.send_schedule_reminders() == 0
    finally:
        current_app.config["IMMINENT_ENABLED"] = True


def test_the_reminder_says_what_and_when(client, booking, ctx):
    from notify import notifications
    date, time = import_one(client, booking, 20)
    notifications.send_schedule_reminders()
    row = sent("schedule_soon")[0]
    assert time in row["subject"]
    assert row["recipient"] == "booker@test.local"


def test_a_row_with_an_unreadable_time_still_gets_a_sentence(client, booking,
                                                             ctx):
    """Import validates the time, so this row can only arrive by somebody
    editing the database. It should still produce a sentence rather than
    throwing inside the sweep, where nothing is watching.

    The window is compared as text in SQL, so the bad value has to sort
    between `now` and the cutoff to be selected at all -- "09:2X" lies
    between "09:13" and "09:43" as a string while failing to parse as a
    time, which is the only shape that reaches the fallback.
    """
    from core import database as db
    from notify import notifications

    db.insert(
        "INSERT INTO schedule_events (user_id, source_id, event_date,"
        " start_time, title, local_clock) VALUES (?, ?, ?, ?, ?, 1)",
        (booking["user"]["id"], "hand-edited", "2026-09-21", "09:2X",
         "Odd class"))

    now = dt.datetime(2026, 9, 21, 9, 13)
    assert notifications.send_schedule_reminders(now=now) == 1
    row = sent("schedule_soon")[0]
    assert "Odd class" in row["subject"]

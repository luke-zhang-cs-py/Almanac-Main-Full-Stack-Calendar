"""
schedule.py
------------
A personal timetable, imported from the standalone planner.

The planner is one HTML file opened from disk. It can show a notification
while its tab is open and nothing at all once it is closed -- a file://
origin cannot register a service worker, so there is no background to run in.
That is the gap this closes: export from the planner, import here, and
Almanac's own sweep emails you before each class whether or not anything is
open.

Not appointments
----------------
A lecture has no second party, no provider to notify and no slot to hold
against double-booking, so it does not belong in `appointments` -- which is
NOT NULL on both provider_id and client_id and carries a unique index on
(provider, date, start) that a timetable would trip over constantly. This is
its own table, owned by one user, with no booking semantics at all.

Re-importing
------------
`source_id` is the planner's own id for the event, and (user_id, source_id)
is unique. The planner's term ids are deterministic -- "term-2026-12-02-1000-
..." -- so importing the same export twice updates rather than duplicates,
and importing a later export moves a class that has been rescheduled rather
than leaving both.

The timezone rule
-----------------
The planner stores a time as written with a timezone *label* beside it. For
nearly everything that label is the local one and the stored time is the
local instant. For anything else -- a fixture at "11:30 EST" -- it is not,
and reminding at that wall-clock time locally would be hours out. Rather
than infer an offset from a two-letter label, those rows are imported and
shown but never reminded about: `local_clock` is decided here, once, at
import. A reminder at a demonstrably wrong time is worse than none.

Why reminded_at, and not email_log
----------------------------------
mailer de-duplicates through a unique index on email_log declared
`WHERE appointment_id IS NOT NULL`, so it de-duplicates nothing for a row
that is not an appointment: every scan across the window would send again.
Adding a column to email_log would not fix it either, because the schema is
CREATE TABLE IF NOT EXISTS and a new column never reaches a database that
already exists. So this table carries its own mark.
"""

import datetime as dt
import logging

import database as db

log = logging.getLogger(__name__)

# What the planner writes at the top of an export. Refusing anything else is
# the difference between "that is not a planner backup" and a stack trace.
PLANNER_APP = "september-planner"

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


class ScheduleError(Exception):
    """Something the caller can fix: not a planner export, a bad date."""


def _last_sunday(year, month):
    """The date of the last Sunday in (year, month).

    The UK clock change rule itself: back on the last Sunday of October,
    forward on the last Sunday of March, every year, forever. Walking
    backwards from the first of the *next* month is simpler than counting
    forward from the day this one has 28-31 of, and needs no calendar table.
    """
    first_of_next_month = (
        dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    )
    last_day = first_of_next_month - dt.timedelta(days=1)
    # date.weekday(): Monday=0 ... Sunday=6. Walking back that far from
    # `last_day` always lands on a Sunday, whatever day of the week
    # `last_day` itself falls on, including when it already is one.
    return last_day - dt.timedelta(days=(last_day.weekday() - 6) % 7)


def uk_zone(date_iso):
    """"BST" or "GMT" for a date, by the actual rule rather than a copied-in
    pair of dates.

    This used to be two literal dates -- "British Summer Time ran to 25
    October 2026 and resumes 28 March 2027" -- good for exactly one winter
    and silently wrong for every one after it, since nothing here re-derives
    them from a calendar. The rule that produces those two dates does not
    change year to year, so it is computed for whichever year the date
    itself falls in instead.
    """
    date = dt.datetime.strptime(date_iso, DATE_FORMAT).date()
    bst_starts = _last_sunday(date.year, 3)
    bst_ends = _last_sunday(date.year, 10)
    return "BST" if bst_starts <= date < bst_ends else "GMT"


def is_local_clock(date_iso, label):
    """Whether a planner event's stored time is the local instant.

    No label means the planner never claimed otherwise, which is the common
    case and is treated as local.
    """
    return not label or label == uk_zone(date_iso)


def _clean_time(value):
    try:
        return dt.datetime.strptime(str(value).strip(), TIME_FORMAT).strftime(
            TIME_FORMAT)
    except (ValueError, TypeError, AttributeError):
        return None


def _clean_date(value):
    try:
        return dt.datetime.strptime(str(value).strip(), DATE_FORMAT).strftime(
            DATE_FORMAT)
    except (ValueError, TypeError, AttributeError):
        return None


def import_payload(user_id, payload, conn=None):
    """Read a planner export into this user's timetable.

    Returns what it did rather than just a count: somebody importing a file
    wants to know whether it added forty classes or updated the two that
    moved, and how many rows it could not read.
    """
    if not isinstance(payload, dict) or payload.get("app") != PLANNER_APP:
        raise ScheduleError(
            "That is not a planner backup. Use Export backup in the planner "
            "and import the file it downloads.")

    events = payload.get("events")
    if not isinstance(events, dict):
        raise ScheduleError("That backup has no events in it.")

    added = updated = skipped = 0
    for raw_date, rows in events.items():
        date = _clean_date(raw_date)
        if not date or not isinstance(rows, list):
            skipped += len(rows) if isinstance(rows, list) else 1
            continue

        for row in rows:
            if not isinstance(row, dict):
                skipped += 1
                continue
            start = _clean_time(row.get("time"))
            source_id = str(row.get("id") or "").strip()
            title = str(row.get("title") or "").strip()
            if not start or not source_id or not title:
                skipped += 1
                continue

            existing = db.query(
                "SELECT id FROM schedule_events "
                "WHERE user_id = ? AND source_id = ?",
                (user_id, source_id), one=True, conn=conn)

            values = (date, start, _clean_time(row.get("end")), title,
                      str(row.get("type") or "") or None,
                      1 if is_local_clock(date, row.get("tz")) else 0)

            if existing:
                # reminded_at is cleared, because a class that has moved is
                # a different moment and deserves its own reminder.
                db.execute(
                    "UPDATE schedule_events SET event_date = ?, start_time = ?,"
                    " end_time = ?, title = ?, kind = ?, local_clock = ?,"
                    " reminded_at = NULL WHERE id = ?",
                    values + (existing["id"],), conn=conn)
                updated += 1
            else:
                db.insert(
                    "INSERT INTO schedule_events (user_id, source_id,"
                    " event_date, start_time, end_time, title, kind,"
                    " local_clock) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, source_id) + values, conn=conn)
                added += 1

    log.info("planner import for user %s: +%s ~%s skip %s",
             user_id, added, updated, skipped)
    return {"added": added, "updated": updated, "skipped": skipped}


def list_for_user(user_id, upcoming_only=False, now=None, conn=None):
    sql = "SELECT * FROM schedule_events WHERE user_id = ?"
    params = [user_id]
    if upcoming_only:
        now = now or dt.datetime.now()
        sql += " AND (event_date || ' ' || start_time) >= ?"
        params.append(now.strftime("%Y-%m-%d %H:%M"))
    return db.query(sql + " ORDER BY event_date, start_time",
                    tuple(params), conn=conn)


def get(event_id, conn=None):
    return db.query("SELECT * FROM schedule_events WHERE id = ?",
                    (event_id,), one=True, conn=conn)


def delete(event_id, owner_id, conn=None):
    existing = get(event_id, conn=conn)
    if not existing or existing["user_id"] != owner_id:
        raise ScheduleError("That is not in your timetable.")
    db.execute("DELETE FROM schedule_events WHERE id = ?", (event_id,),
               conn=conn)


def clear(user_id, conn=None):
    """Drop the whole imported timetable. The planner is the source of
    truth, so starting again from a fresh export is a normal thing to do."""
    rows = list_for_user(user_id, conn=conn)
    db.execute("DELETE FROM schedule_events WHERE user_id = ?", (user_id,),
               conn=conn)
    return len(rows)


def due_for_reminder(now, minutes, conn=None):
    """Rows starting within `minutes` that have not been reminded about.

    The window starts at `now`, so something already under way is not
    chased. Rows on another clock are excluded here rather than filtered by
    the caller, so there is one place that decision is made.
    """
    cutoff = now + dt.timedelta(minutes=minutes)
    return db.query(
        "SELECT s.*, u.email AS user_email, u.name AS user_name "
        "FROM schedule_events s JOIN users u ON u.id = s.user_id "
        "WHERE s.reminded_at IS NULL AND s.local_clock = 1 "
        "AND (s.event_date || ' ' || s.start_time) BETWEEN ? AND ? "
        "ORDER BY s.event_date, s.start_time",
        (now.strftime("%Y-%m-%d %H:%M"), cutoff.strftime("%Y-%m-%d %H:%M")),
        conn=conn)


def mark_reminded(event_id, when=None, conn=None):
    db.execute("UPDATE schedule_events SET reminded_at = ? WHERE id = ?",
               ((when or dt.datetime.now()).strftime(
                   db.TIMESTAMP_FORMAT), event_id), conn=conn)


def view(row):
    """One row, for the wire. camel_keys does the renaming."""
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "title": row["title"],
        "kind": row["kind"],
        "local_clock": bool(row["local_clock"]),
        "reminded_at": row["reminded_at"],
    }

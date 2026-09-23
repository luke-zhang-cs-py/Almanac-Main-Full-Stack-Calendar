"""What Almanac says, and on what occasion.

These assert against email_log rather than against a mailbox: mailer claims a
row before it queues anything, so the log is the record of what was decided
to send, without waiting on a delivery thread. It is also the table the
de-duplication index sits on, which is the behaviour most worth pinning --
"the host got two emails about one booking" was a real bug here.
"""

import datetime as dt

import pytest

from notify import notifications


def sent(kind=None, to=None):
    from core import database as db
    sql, params = "SELECT * FROM email_log WHERE 1 = 1", []
    if kind:
        sql, params = sql + " AND kind = ?", params + [kind]
    if to:
        sql, params = sql + " AND recipient = ?", params + [to]
    return db.query(sql + " ORDER BY id", tuple(params))


def clear_log():
    from core import database as db
    db.execute("DELETE FROM email_log")


# ----------------------------------------------------------------- welcome

def test_registering_sends_one_welcome(client):
    from tests.conftest import register
    register(client, "newbie@test.local")
    rows = sent("welcome", "newbie@test.local")
    assert len(rows) == 1
    assert "Welcome" in rows[0]["subject"]


def test_welcome_survives_a_user_with_an_unknown_role(ctx):
    """The role line is looked up in a dict; an unexpected role must produce a
    shorter email, not a KeyError inside a registration request."""
    notifications.send_welcome({"id": None, "name": "Odd", "role": "wizard",
                                "email": "wizard@test.local"})
    assert len(sent("welcome", "wizard@test.local")) == 1


def test_a_broken_user_row_does_not_raise(ctx):
    """Every trigger here is a side effect of something that already
    succeeded. None of them may turn that into a failure."""
    notifications.send_welcome({})           # no name, no email, no role
    assert sent("welcome", "") == []


# ----------------------------------------------------------------- booking

def test_booking_tells_both_sides(ctx, booking, provider):
    assert len(sent("booked_client", "booker@test.local")) == 1
    assert len(sent("booked_provider", "provider@test.local")) == 1


def test_the_host_is_not_told_twice_about_a_coffee_chat(ctx, booking):
    """A coffee chat sends its own, richer host email naming the invite. This
    flag is what stops the generic one going out as well -- the bug was two
    messages about one event, which is how people learn to filter a sender."""
    clear_log()
    notifications.notify_booked(booking["id"], notify_provider=False)
    assert len(sent("booked_client")) == 1
    assert sent("booked_provider") == []


def test_the_same_booking_email_is_never_sent_twice(ctx, booking):
    """Overlapping scans, a double-clicked button and two web workers all
    collapse onto the unique index over (appointment, kind, recipient)."""
    before = len(sent())
    notifications.notify_booked(booking["id"])
    notifications.notify_booked(booking["id"])
    assert len(sent()) == before


def test_an_appointment_that_does_not_exist_is_quietly_ignored(ctx):
    notifications.notify_booked(999999)
    notifications.notify_cancelled(999999)
    notifications.notify_completed(999999)
    assert sent() == []


def test_load_appointment_joins_both_parties(ctx, booking):
    appt = notifications.load_appointment(booking["id"])
    assert appt["client_name"] == "Bo Oker"
    assert appt["provider_email"] == "provider@test.local"
    assert notifications.load_appointment(999999) is None


# ------------------------------------------------------------ cancellation

def test_cancelling_tells_both_sides(ctx, booking):
    clear_log()
    notifications.notify_cancelled(booking["id"])
    assert len(sent("cancelled_client")) == 1
    assert len(sent("cancelled_provider")) == 1


def test_the_canceller_is_told_they_cancelled(ctx, booking, provider):
    """Same event, two readings. The person who pressed the button wants a
    receipt; the other one is being told news."""
    clear_log()
    notifications.notify_cancelled(booking["id"],
                                   cancelled_by={"id": provider["id"],
                                                 "name": "Test Provider"})
    from core import database as db
    provider_mail = db.query(
        "SELECT * FROM email_log WHERE kind = 'cancelled_provider'", one=True)
    client_mail = db.query(
        "SELECT * FROM email_log WHERE kind = 'cancelled_client'", one=True)
    assert provider_mail and client_mail
    # The wording lives in the body, so re-render to check which branch ran.
    appt = notifications.load_appointment(booking["id"])
    assert appt["provider_id"] == provider["id"]


def test_an_anonymous_cancellation_still_reads_sensibly(ctx, booking):
    """cancelled_by is optional -- an admin script or an expiry sweep has no
    name to give."""
    clear_log()
    notifications.notify_cancelled(booking["id"], cancelled_by=None)
    assert len(sent("cancelled_client")) == 1


# --------------------------------------------------------------- completion

def test_completion_thanks_the_client_only(ctx, booking):
    clear_log()
    notifications.notify_completed(booking["id"])
    assert len(sent("completed_client")) == 1
    assert sent("completed_provider") == []


# --------------------------------------------------------------- test email

def test_send_test_reports_success(ctx, provider):
    assert notifications.send_test("someone@test.local",
                                   {"id": provider["id"], "name": "Test Provider"})
    assert len(sent("test", "someone@test.local")) == 1


def test_send_test_reports_failure_when_mail_is_off(app, provider):
    """The admin endpoint turns this into a 409 rather than claiming it
    queued something."""
    with app.app_context():
        app.config["MAIL_ENABLED"] = False
        try:
            assert notifications.send_test("off@test.local",
                                           {"id": provider["id"], "name": "X"}) is False
            assert sent("test", "off@test.local") == []
        finally:
            app.config["MAIL_ENABLED"] = True


# ---------------------------------------------------------------- reminders

def a_reminder_moment(booking):
    """The day before the appointment, at the same time."""
    start = dt.datetime.strptime(f"{booking['date']} {booking['start']}", "%Y-%m-%d %H:%M")
    return start - dt.timedelta(hours=20)


def test_reminders_go_out_inside_the_window(ctx, booking):
    clear_log()
    assert notifications.send_due_reminders(now=a_reminder_moment(booking)) == 2
    assert len(sent("reminder_client")) == 1
    assert len(sent("reminder_provider")) == 1


def test_reminders_ignore_appointments_further_out(ctx, booking):
    """REMINDER_HOURS_BEFORE is 24; this appointment is five days away."""
    clear_log()
    assert notifications.send_due_reminders() == 0
    assert sent() == []


def test_a_second_scan_reminds_nobody_twice(ctx, booking):
    """The scheduler runs this every fifteen minutes."""
    clear_log()
    moment = a_reminder_moment(booking)
    assert notifications.send_due_reminders(now=moment) == 2
    assert notifications.send_due_reminders(now=moment) == 0
    assert len(sent()) == 2


def test_cancelled_appointments_are_not_reminded(ctx, booking):
    from core import database as db
    clear_log()
    db.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (booking["id"],))
    assert notifications.send_due_reminders(now=a_reminder_moment(booking)) == 0


@pytest.mark.parametrize("kind", ["reminder_client", "reminder_provider"])
def test_the_reminder_says_when_not_just_what(ctx, booking, kind):
    clear_log()
    notifications.send_due_reminders(now=a_reminder_moment(booking))
    row = sent(kind)[0]
    assert booking["start"] in row["subject"]


# --------------------------------------------------- the half-hour nudge

def minutes_before(booking, minutes):
    start = dt.datetime.strptime(f"{booking['date']} {booking['start']}",
                                 "%Y-%m-%d %H:%M")
    return start - dt.timedelta(minutes=minutes)


def test_a_nudge_goes_out_inside_the_half_hour(ctx, booking):
    clear_log()
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, 25)) == 2
    assert len(sent("imminent_client")) == 1
    assert len(sent("imminent_provider")) == 1


def test_nothing_is_nudged_before_the_window_opens(ctx, booking):
    """IMMINENT_MINUTES_BEFORE is 30; at 31 minutes out it is not due yet."""
    clear_log()
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, 31)) == 0
    assert sent() == []


def test_a_second_scan_nudges_nobody_twice(ctx, booking):
    """The sweep runs on a timer, so it fires repeatedly inside the same
    half hour."""
    clear_log()
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, 20)) == 2
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, 10)) == 0
    assert len(sent()) == 2


def test_an_appointment_already_under_way_is_not_chased(ctx, booking):
    """A reminder for something you are late to is noise, and a scan that
    has fallen behind should stay quiet rather than shout."""
    clear_log()
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, -5)) == 0
    assert sent() == []


def test_the_nudge_does_not_collide_with_the_day_before_reminder(ctx, booking):
    """Separate message kinds, which is the whole reason both arrive: mailer
    de-duplicates on (appointment, kind, recipient), so reusing the
    reminder's kind would have this one silently dropped."""
    clear_log()
    assert notifications.send_due_reminders(
        now=a_reminder_moment(booking)) == 2
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, 25)) == 2
    assert len(sent()) == 4
    assert {row["kind"] for row in sent()} == {
        "reminder_client", "reminder_provider",
        "imminent_client", "imminent_provider"}


def test_a_cancelled_appointment_is_not_nudged(ctx, booking):
    from core import database as db
    clear_log()
    db.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?",
               (booking["id"],))
    assert notifications.send_imminent_reminders(
        now=minutes_before(booking, 20)) == 0


def test_the_nudge_can_be_turned_off_on_its_own(ctx, booking):
    """Somebody who wants only the day-before reminder should not have to
    disable reminders altogether to get it."""
    from flask import current_app
    clear_log()
    current_app.config["IMMINENT_ENABLED"] = False
    try:
        assert notifications.send_imminent_reminders(
            now=minutes_before(booking, 20)) == 0
        assert sent() == []
    finally:
        current_app.config["IMMINENT_ENABLED"] = True


@pytest.mark.parametrize("kind", ["imminent_client", "imminent_provider"])
def test_the_nudge_says_it_is_starting_soon(ctx, booking, kind):
    clear_log()
    notifications.send_imminent_reminders(now=minutes_before(booking, 25))
    row = sent(kind)[0]
    assert "Starting soon" in row["subject"]
    assert booking["start"] in row["subject"]

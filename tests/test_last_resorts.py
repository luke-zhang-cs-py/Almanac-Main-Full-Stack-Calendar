"""The arms that only run when something below has already gone wrong.

Three groups, and none of them is reachable by using the application
normally -- which is exactly why they are worth executing at least once:

  * **Mail that raises.** Every notification swallows its own exception, on
    the principle that a mail problem must not turn a successful booking
    into an error for the person who made it. Swallowing is only correct if
    it actually swallows; an exception escaping `notify_booked` would fail
    the booking that already happened.

  * **The PostgreSQL driver.** The suite runs on SQLite, so every
    `if _IS_POSTGRES` branch -- the connection, the `RETURNING id` insert,
    the `?`-to-`%s` rewrite -- has never executed. A fake driver runs them
    without a server, which is worth more than leaving the production path
    untested.

  * **Guards that fail closed.** A permission check whose final `return
    False` never runs is a permission check nobody has watched refuse.
"""

import sqlite3
import types

import pytest


# ------------------------------------------------------- mail that raises


@pytest.fixture
def exploding_mail(monkeypatch):
    """mailer.send raises, from wherever it is called."""
    from notify import coffee_notifications
    from notify import mailer
    from notify import notifications

    def boom(message):
        raise RuntimeError("the mail server fell over")

    for module in (mailer, notifications, coffee_notifications):
        if hasattr(module, "send"):
            monkeypatch.setattr(module, "send", boom, raising=False)
    monkeypatch.setattr(mailer, "send", boom)
    return boom


def test_a_booking_survives_the_confirmation_email_failing(
        client, provider, booking, exploding_mail):
    """The appointment is already in the database by this point. Letting the
    exception out would report a failure for something that succeeded."""
    from notify import notifications
    notifications.notify_booked(booking["id"])          # must not raise


def test_a_cancellation_survives_its_email_failing(client, booking,
                                                   exploding_mail):
    from notify import notifications
    notifications.notify_cancelled(booking["id"])


def test_a_completion_survives_its_email_failing(client, booking,
                                                 exploding_mail):
    from notify import notifications
    notifications.notify_completed(booking["id"])


def an_invite(client, provider, email="mail@test.local"):
    return client.post("/api/coffee/invites", json={"email": email},
                       headers=provider["auth"]).get_json()["invite"]


def test_the_four_coffee_emails_all_swallow_their_own_failures(
        client, provider, ctx, exploding_mail):
    from domain import coffee_chats
    from notify import coffee_notifications

    invite = an_invite(client, provider, "swallow@test.local")

    coffee_notifications.send_invite(invite["id"])
    coffee_notifications.send_nudge(invite["id"])
    coffee_notifications.notify_declined(invite["id"])

    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    day = next(d for d in slots if d["slots"])
    _row, appointment_id = coffee_chats.book(invite["token"], day["date"],
                                             day["slots"][0]["start"])
    coffee_notifications.notify_booked(invite["id"])


def test_the_booked_email_gives_up_quietly_if_the_appointment_is_gone(
        client, provider, ctx):
    """The invite says it was booked but the appointment row has since been
    deleted. There is nothing to describe, so it returns rather than
    rendering an email full of blanks."""
    from notify import coffee_notifications

    from core import database as db

    invite = an_invite(client, provider, "vanished@test.local")
    # Marked booked with nothing to point at. A foreign key stops the row
    # naming an appointment that does not exist, so the state to reproduce
    # is the one the database does allow: booked, appointment_id NULL.
    db.execute("UPDATE coffee_invites SET status = 'booked' WHERE id = ?",
               (invite["id"],))
    coffee_notifications.notify_booked(invite["id"])      # must not raise


# ------------------------------------------------------ the slot generator


def test_a_day_whose_slots_cannot_be_computed_is_skipped(client, provider,
                                                         ctx, monkeypatch):
    """One unusable day must not empty the whole guest page."""
    from domain import coffee_chats

    invite = coffee_chats.get_invite(an_invite(client, provider,
                                               "skip@test.local")["id"])
    real = coffee_chats.slot_starts_for
    calls = {"n": 0}

    def sometimes(provider_id, day_str, duration):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("unreadable window")
        return real(provider_id, day_str, duration)

    monkeypatch.setattr(coffee_chats, "slot_starts_for", sometimes)
    days = coffee_chats.available_slots(invite)
    assert calls["n"] > 1, "it stopped at the bad day instead of carrying on"
    assert days, "the remaining days should still be offered"


# ------------------------------------------------------ guards failing closed


def test_a_role_that_is_none_of_the_three_may_not_act(app, booking):
    """_may_act_on lists the roles that may act rather than the ones that may
    not, so an unknown role falls through to False. Missing that line means
    a permission check that fails open."""
    from flask import g
    from routes import appointment_routes

    with app.test_request_context():
        g.current_user = {"id": booking["user"]["id"], "role": "auditor"}
        assert appointment_routes._may_act_on(
            {"client_id": booking["user"]["id"], "provider_id": 1}) is False


def test_completing_an_appointment_that_does_not_exist(client, provider):
    got = client.post("/api/appointments/999999/complete",
                      headers=provider["auth"])
    assert got.status_code == 404


def test_a_day_off_with_a_malformed_time_is_refused(client, provider):
    """The block validator, which is a different function from the one that
    checks recurring hours and had never been reached with a bad clock."""
    got = client.post("/api/availability/mine/block",
                      json={"date": "2026-12-24", "start_time": "9am",
                            "end_time": "5pm"},
                      headers=provider["auth"])
    assert got.status_code == 400
    assert "HH:MM" in got.get_json()["error"]


# --------------------------------------------------------- the pg driver


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        self.conn.statements.append((sql, params))

    def fetchone(self):
        return [4242]

    def close(self):
        self.conn.closed_cursors += 1


class FakeConnection:
    def __init__(self, *a, **kw):
        self.args, self.kwargs = a, kw
        self.statements = []
        self.commits = 0
        self.closed = False
        self.closed_cursors = 0
        self.autocommit = None

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


@pytest.fixture
def as_postgres(monkeypatch):
    """Make core/database.py take its PostgreSQL branches, with a fake driver.

    The module decides once at import which backend it is on, so the flag is
    flipped rather than the URL changed -- and monkeypatch puts it back, so
    the rest of the suite is still on SQLite.
    """
    from core import database as db

    made = []

    def connect(url, cursor_factory=None):
        conn = FakeConnection(url, cursor_factory=cursor_factory)
        made.append(conn)
        return conn

    fake = types.ModuleType("psycopg2")
    fake.connect = connect
    fake.IntegrityError = sqlite3.IntegrityError
    extras = types.ModuleType("psycopg2.extras")
    extras.DictCursor = object()
    fake.extras = extras

    monkeypatch.setitem(__import__("sys").modules, "psycopg2", fake)
    monkeypatch.setitem(__import__("sys").modules, "psycopg2.extras", extras)
    monkeypatch.setattr(db, "_IS_POSTGRES", True)
    return made


def test_placeholders_are_rewritten_for_postgres(as_postgres):
    """SQLite takes ?, psycopg2 takes %s. One query text is written; this is
    the only place that difference is allowed to exist."""
    from core import database as db

    assert db._adapt_sql("SELECT * FROM users WHERE id = ?") == \
        "SELECT * FROM users WHERE id = %s"
    assert db._adapt_sql("INSERT INTO t (a, b) VALUES (?, ?)") == \
        "INSERT INTO t (a, b) VALUES (%s, %s)"


def test_a_postgres_connection_is_opened_without_autocommit(as_postgres):
    """Every write in this app is meant to be inside a transaction it
    controls, so autocommit must be off."""
    from core import database as db

    conn = db._new_connection()
    assert conn.autocommit is False
    assert conn.kwargs["cursor_factory"] is not None


def test_an_insert_asks_postgres_to_return_the_id(as_postgres):
    """lastrowid does not exist there, so the id has to be asked for."""
    from core import database as db

    conn = FakeConnection()
    new_id = db.insert("INSERT INTO users (name) VALUES (?)", ("Ada",),
                       conn=conn)
    assert new_id == 4242
    sql, _params = conn.statements[0]
    assert sql.endswith("RETURNING id")
    assert "%s" in sql, "the placeholder should have been rewritten"


def test_a_script_runs_as_one_statement_on_postgres(as_postgres):
    from core import database as db

    conn = FakeConnection()
    db.executescript("CREATE TABLE a (id INT); CREATE TABLE b (id INT);",
                     conn=conn)
    assert len(conn.statements) == 1, "psycopg2 takes the whole script at once"
    assert conn.commits == 1


def test_the_script_helper_closes_what_it_opened(as_postgres):
    """standalone_connection() is what seed scripts use outside a Flask
    app context. A leaked connection there holds a transaction open."""
    from core import database as db

    with db.standalone_connection() as conn:
        assert conn.closed is False
    assert conn.closed is True


def test_the_host_email_gives_up_if_the_appointment_row_is_gone(
        client, provider, ctx):
    """appointment_id survives, the appointment does not.

    The foreign key is ON DELETE SET NULL, so deleting the appointment
    normally clears the column and the earlier guard catches it. The state
    this line is written for -- a dangling id -- therefore has to be made
    with the key relaxed for one statement.
    """
    from domain import coffee_chats
    from notify import coffee_notifications
    from core import database as db

    invite = an_invite(client, provider, "dangling@test.local")
    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    day = next(d for d in slots if d["slots"])
    _row, appointment_id = coffee_chats.book(invite["token"], day["date"],
                                             day["slots"][0]["start"])

    conn = db.get_db()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    coffee_notifications.notify_booked(invite["id"])      # must not raise


def test_two_bookings_that_pass_the_free_check_still_cannot_collide(
        client, provider, booking, monkeypatch):
    """The unique index is the thing that actually prevents a double
    booking; is_slot_free is only an early, friendlier no.

    Forcing the check to pass is how the race is reproduced without two real
    clients: the second insert hits the index, and the route has to turn that
    into a 409 rather than a 500.
    """
    from routes import appointment_routes

    monkeypatch.setattr(appointment_routes, "is_slot_free",
                        lambda *a, **kw: True)

    got = client.post("/api/appointments", headers=booking["auth"], json={
        "provider_id": provider["id"], "date": booking["date"],
        "start_time": booking["start"], "end_time": booking["end"]})

    assert got.status_code == 409
    assert "just booked by someone else" in got.get_json()["error"]


def test_a_postgres_integrity_error_is_caught_too(monkeypatch):
    """Both modules build their INTEGRITY_ERRORS tuple at import, and the
    psycopg2 half has never been built here because the driver is not
    installed. If that tuple were wrong, a Postgres deployment would answer a
    double-booking with a 500 instead of a 409, and nothing in a SQLite run
    would ever say so.

    The source is executed in a throwaway namespace rather than reloaded.
    importlib.reload swaps a live module's globals underneath anything using
    them, and mailer has a delivery thread running inside the test session --
    the first version of this test reloaded it and left that thread raising.
    Compiling against the real filename keeps the executed lines attributed
    to the real module, so this still counts as covering them.
    """
    import io as _io
    import sys

    class FakeIntegrityError(Exception):
        pass

    fake = types.ModuleType("psycopg2")
    fake.IntegrityError = FakeIntegrityError
    extras = types.ModuleType("psycopg2.extras")
    extras.DictCursor = object()
    fake.extras = extras

    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)

    from notify import mailer
    from routes import appointment_routes

    for module in (mailer, appointment_routes):
        with _io.open(module.__file__, encoding="utf-8") as handle:
            source = handle.read()
        namespace = {"__name__": module.__name__ + "_probe",
                     "__file__": module.__file__}
        exec(compile(source, module.__file__, "exec"), namespace)

        errors = namespace["INTEGRITY_ERRORS"]
        assert FakeIntegrityError in errors, (
            f"{module.__name__} would not catch a Postgres integrity error")
        assert sqlite3.IntegrityError in errors, (
            "and it must still catch the SQLite one")

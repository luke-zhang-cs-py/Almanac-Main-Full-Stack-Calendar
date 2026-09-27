"""The invite paths that only happen when something has gone wrong.

test_coffee_chats.py walks the lifecycle as it is meant to go. This is the
other half: the link that expired between the email and the click, the guest
who books the slot somebody else just took, the payload with a duration of
"soon". Each of these is a sentence a real guest can end up reading, so each
is worth being sure of -- and none of them was executed by the suite before.

The expiry and race cases cannot be produced by calling the API in order, so
they are set up by writing the state directly and then calling the same
function the route calls. That is deliberate: faking the *clock* would test a
fake, while writing an expired row tests the check.
"""

import datetime as dt

import pytest

from domain import coffee_chats
from domain.coffee_chats import InviteError


def an_invite(client, provider, **over):
    body = {"email": "guest@test.local"}
    body.update(over)
    res = client.post("/api/coffee/invites", json=body, headers=provider["auth"])
    assert res.status_code in (200, 201), res.get_json()
    return res.get_json()["invite"]


# ------------------------------------------------------- the request shape


def test_a_duration_that_is_not_a_number_is_refused(ctx):
    with pytest.raises(InviteError) as raised:
        coffee_chats.InviteRequest.from_payload(
            {"email": "a@test.local", "duration": "soon"})
    assert "number of minutes" in str(raised.value)


def test_a_duration_off_the_allowed_list_is_refused(ctx, provider):
    """The grid only has 15/30/45/60 in it, so 37 minutes is not a booking
    anybody could ever take."""
    request = coffee_chats.InviteRequest.from_payload(
        {"email": "odd@test.local", "duration": 37})
    with pytest.raises(InviteError) as raised:
        coffee_chats.create_invite(provider["id"], request)
    assert "37" in str(raised.value) or "duration" in str(raised.value).lower()


def test_an_invite_for_a_host_who_does_not_exist(ctx):
    request = coffee_chats.InviteRequest.from_payload({"email": "x@test.local"})
    with pytest.raises(InviteError) as raised:
        coffee_chats.create_invite(999999, request)
    assert "Host not found" in str(raised.value)


# ------------------------------------------------------------- the listing


def test_listing_by_status(client, provider, ctx):
    """The host dashboard filters; the unfiltered path was the only one the
    suite had been taking."""
    an_invite(client, provider, email="one@test.local")
    an_invite(client, provider, email="two@test.local")

    everything = coffee_chats.list_for_host(provider["id"])
    sent = coffee_chats.list_for_host(provider["id"], status="sent")
    booked = coffee_chats.list_for_host(provider["id"], status="booked")

    assert len(everything) == 2
    assert len(sent) == 2
    assert booked == []


# -------------------------------------------------------------- expiry


def test_an_unreadable_expiry_is_treated_as_not_expired(ctx):
    """A row whose timestamp cannot be parsed should not lock somebody out.
    Refusing every invite because one column is malformed is the worse of
    the two failures."""
    assert coffee_chats._is_expired({"expires_at": "not a timestamp"}) is False
    assert coffee_chats._is_expired({"expires_at": None}) is False


def test_an_expired_link_says_so_and_marks_itself(client, provider, ctx):
    from core import database as db

    invite = an_invite(client, provider, email="late@test.local")
    db.execute("UPDATE coffee_invites SET expires_at = ? WHERE id = ?",
               ((dt.datetime.now() - dt.timedelta(days=1)).isoformat(),
                invite["id"]))

    with pytest.raises(InviteError) as raised:
        coffee_chats._open_invite_for(invite["token"])
    assert "expired" in str(raised.value)

    # And the row is left saying so, rather than expiring again on every click.
    assert coffee_chats.get_invite(invite["id"])["status"] == "expired"


def test_a_revoked_link_is_no_longer_active(client, provider, ctx):
    invite = an_invite(client, provider, email="gone@test.local")
    coffee_chats.revoke(invite["id"], provider["id"])
    with pytest.raises(InviteError) as raised:
        coffee_chats._open_invite_for(invite["token"])
    assert "no longer active" in str(raised.value)


def test_a_token_nobody_issued(ctx):
    with pytest.raises(InviteError) as raised:
        coffee_chats._open_invite_for("not-a-real-token")
    assert "not valid" in str(raised.value)


def test_a_link_already_used_to_book(client, provider, ctx):
    invite = an_invite(client, provider, email="done@test.local")
    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    day = next(d for d in slots if d["slots"])
    coffee_chats.book(invite["token"], day["date"], day["slots"][0]["start"])

    with pytest.raises(InviteError) as raised:
        coffee_chats._open_invite_for(invite["token"])
    assert "already been used" in str(raised.value)


# -------------------------------------------------------------- booking


def test_a_note_from_the_guest_reaches_the_appointment(client, provider, ctx):
    from core import database as db

    invite = an_invite(client, provider, email="chatty@test.local")
    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    day = next(d for d in slots if d["slots"])
    _row, appointment_id = coffee_chats.book(
        invite["token"], day["date"], day["slots"][0]["start"],
        guest_name="Ada", note="  Running five minutes late  ")

    notes = db.query("SELECT notes FROM appointments WHERE id = ?",
                     (appointment_id,), one=True)["notes"]
    assert "From Ada: Running five minutes late" in notes
    assert notes.strip().endswith("late"), "the note should be stripped"


def test_losing_the_race_for_a_slot_is_a_sentence_not_a_500(
        client, provider, ctx, monkeypatch):
    """Two guests can pass the free-slot check and then both insert. The
    unique index is what actually prevents the double-booking; this is the
    backstop that turns its error into something a guest can read."""
    from core import database as db

    invite = an_invite(client, provider, email="racer@test.local")
    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    day = next(d for d in slots if d["slots"])

    real_insert = db.insert

    def insert_then_collide(sql, params=(), conn=None):
        if "INSERT INTO appointments" in sql:
            raise RuntimeError("UNIQUE constraint failed: uniq_active_slot")
        return real_insert(sql, params, conn=conn)

    monkeypatch.setattr(db, "insert", insert_then_collide)

    with pytest.raises(InviteError) as raised:
        coffee_chats.book(invite["token"], day["date"],
                          day["slots"][0]["start"])
    assert "just took that slot" in str(raised.value)


# -------------------------------------------------------------- declining


def test_declining_a_token_nobody_issued(ctx):
    with pytest.raises(InviteError):
        coffee_chats.decline("no-such-token")


def test_declining_something_already_booked(client, provider, ctx):
    invite = an_invite(client, provider, email="both@test.local")
    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    day = next(d for d in slots if d["slots"])
    coffee_chats.book(invite["token"], day["date"], day["slots"][0]["start"])

    with pytest.raises(InviteError) as raised:
        coffee_chats.decline(invite["token"])
    assert "already been used" in str(raised.value)


# ------------------------------------------------- found by the second audit


def first_open_day(invite):
    slots = coffee_chats.available_slots(coffee_chats.get_invite(invite["id"]))
    return next(d for d in slots if len(d["slots"]) > 4)


def test_one_link_books_one_time_even_when_two_requests_race(
        client, provider, ctx, monkeypatch):
    """A token authorises one booking. Two requests on the same link -- a
    double-submit, two tabs -- used to both read the invite as open before
    either had written, and both went on to book, at different times, so the
    host held two slots for one guest and the invite named only one. Here
    the second request is handed the invite as it was before the first one
    booked, which is that race with the timing fixed."""
    from core import database as db

    invite = an_invite(client, provider, email="twice@test.local")
    day = first_open_day(invite)
    stale = coffee_chats.get_by_token(invite["token"])

    coffee_chats.book(invite["token"], day["date"], day["slots"][0]["start"])
    monkeypatch.setattr(coffee_chats, "_open_invite_for", lambda token: stale)
    with pytest.raises(InviteError) as raised:
        coffee_chats.book(invite["token"], day["date"], day["slots"][4]["start"])
    assert "already been used" in str(raised.value)

    booked = db.query("SELECT id FROM appointments WHERE provider_id = ? "
                      "AND status = 'confirmed'", (provider["id"],))
    assert len(booked) == 1


def test_a_lost_slot_leaves_the_link_usable(client, provider, ctx, monkeypatch):
    """The invite is claimed before the insert. When the insert then loses
    to the unique index, the claim is given back, or the guest's one link
    would be spent on a booking that never happened."""
    from core import database as db

    invite = an_invite(client, provider, email="retry@test.local")
    day = first_open_day(invite)
    real_insert = db.insert

    def collide(sql, params=(), conn=None):
        if "INSERT INTO appointments" in sql:
            raise RuntimeError("UNIQUE constraint failed: uniq_active_slot")
        return real_insert(sql, params, conn=conn)

    monkeypatch.setattr(db, "insert", collide)
    with pytest.raises(InviteError):
        coffee_chats.book(invite["token"], day["date"], day["slots"][0]["start"])
    monkeypatch.setattr(db, "insert", real_insert)

    assert coffee_chats.get_invite(invite["id"])["status"] == "sent"
    _row, appointment_id = coffee_chats.book(
        invite["token"], day["date"], day["slots"][1]["start"])
    assert appointment_id


def test_an_unpadded_hour_books_rather_than_being_told_it_was_taken(
        client, provider, ctx):
    """strptime reads "9:15" as a time, and the slot engine compares padded
    strings, so "9:15" matched no slot and the guest was told somebody had
    just taken a time nobody had."""
    invite = an_invite(client, provider, email="unpadded@test.local")
    day = next(d for d in coffee_chats.available_slots(
        coffee_chats.get_invite(invite["id"])) if any(
            s["start"] == "09:15" for s in d["slots"]))
    _row, appointment_id = coffee_chats.book(invite["token"], day["date"], "9:15")
    from core import database as db
    got = db.query("SELECT start_time FROM appointments WHERE id = ?",
                   (appointment_id,), one=True)
    assert got["start_time"] == "09:15"


def test_a_guest_cannot_overlap_a_booking_made_during_their_check(
        client, provider, ctx, monkeypatch):
    """The logged-in path's overlap race, on the guest path. A rival books
    09:30-10:00 right after the guest's free check for 09:00-10:00 passes;
    different starts, so the unique index lets both in. The check is now
    repeated under the write lock, and the rival cannot write while it is
    held."""
    import sqlite3
    from core import database as db
    from core.config import Config
    from tests.conftest import register

    invite = an_invite(client, provider, email="overlap@test.local", duration=60)
    day = next(d for d in coffee_chats.available_slots(
        coffee_chats.get_invite(invite["id"])) if any(
            s["start"] == "09:00" for s in d["slots"]))
    _token, rival_user = register(client, "rival-guest@test.local")
    real = coffee_chats.is_slot_free

    def check_then_rival_books(*args):
        verdict = real(*args)
        rival = sqlite3.connect(Config.DATABASE_URL.replace("sqlite:///", "", 1),
                                timeout=0.2)
        try:
            rival.execute(
                "INSERT INTO appointments (provider_id, client_id, date, "
                "start_time, end_time) VALUES (?, ?, ?, '09:30', '10:00')",
                (provider["id"], rival_user["id"], day["date"]))
            rival.commit()
        except sqlite3.Error:
            pass                       # locked out, or already in
        finally:
            rival.close()
        return verdict

    monkeypatch.setattr(coffee_chats, "is_slot_free", check_then_rival_books)
    try:
        coffee_chats.book(invite["token"], day["date"], "09:00")
    except InviteError:
        pass

    rows = db.query("SELECT start_time FROM appointments WHERE provider_id = ? "
                    "AND date = ? AND status = 'confirmed'",
                    (provider["id"], day["date"]))
    assert len(rows) == 1, rows

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

import coffee_chats
from coffee_chats import InviteError


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
    import database as db

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
    import database as db

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
    import database as db

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

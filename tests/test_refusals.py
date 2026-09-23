"""What every endpoint says when it has to say no.

Routes are mostly tested down their happy path, which leaves the `except`
arm of each one -- the branch that decides whether a failure is a 400 or a
404, and what sentence the caller reads -- as the part nothing executes. A
wrong status code there is invisible until a client has to distinguish
"you sent nonsense" from "that is gone".

Several of these produce a failure by calling the route with a payload the
domain layer rejects, which is the honest way round: the route is being asked
to translate a real domain error, not a mocked one.
"""

import datetime as dt


# ----------------------------------------------------------- the catalogue


def test_a_non_numeric_price_is_a_400(client, provider, offering):
    got = client.patch(f"/api/offerings/mine/{offering['id']}",
                       json={"priceCents": "free please"},
                       headers=provider["auth"])
    assert got.status_code == 400
    assert "whole number" in got.get_json()["error"]


def test_patching_an_offering_that_is_not_yours_is_a_404(client, provider,
                                                         offering, admin):
    got = client.patch(f"/api/offerings/mine/{offering['id']}",
                       json={"title": "Mine now"}, headers=admin["auth"])
    assert got.status_code == 404


def test_patching_to_something_invalid_is_a_400(client, provider, offering):
    """A negative price is a bad request, not a missing offering -- the
    route has to tell those apart from one exception type."""
    got = client.patch(f"/api/offerings/mine/{offering['id']}",
                       json={"priceCents": -500}, headers=provider["auth"])
    assert got.status_code == 400


def test_hiding_an_offering_that_is_not_yours_is_a_404(client, offering, admin):
    got = client.delete(f"/api/offerings/mine/{offering['id']}",
                        headers=admin["auth"])
    assert got.status_code == 404


def test_the_price_range_of_a_catalogue_with_no_paid_items(client, provider):
    """Every offering free: the label is a word, not an empty range."""
    client.post("/api/offerings/mine",
                json={"title": "Intro chat", "priceCents": 0},
                headers=provider["auth"])
    body = client.get(f"/api/providers/{provider['id']}/offerings").get_json()
    assert body["priceRange"]["label"] == "Free"


def test_the_price_range_spans_cheapest_to_dearest(client, provider):
    for cents in (4500, 15000):
        client.post("/api/offerings/mine",
                    json={"title": f"Session {cents}", "priceCents": cents},
                    headers=provider["auth"])
    label = client.get(
        f"/api/providers/{provider['id']}/offerings").get_json()["priceRange"]["label"]
    assert "45" in label and "150" in label and "–" in label


# --------------------------------------------------------- coffee invites


def test_an_invite_with_a_bad_duration_is_a_400(client, provider):
    got = client.post("/api/coffee/invites",
                      json={"email": "x@test.local", "duration": 37},
                      headers=provider["auth"])
    assert got.status_code == 400


def test_nudging_a_closed_invite_is_refused(client, provider):
    """Revoked, so there is nobody left to chase."""
    made = client.post("/api/coffee/invites", json={"email": "shut@test.local"},
                       headers=provider["auth"]).get_json()["invite"]
    client.delete(f"/api/coffee/invites/{made['id']}", headers=provider["auth"])

    got = client.post(f"/api/coffee/invites/{made['id']}/nudge",
                      headers=provider["auth"])
    assert got.status_code == 400
    assert "no longer open" in got.get_json()["error"]


def test_revoking_somebody_elses_invite_is_a_404(client, provider, admin):
    made = client.post("/api/coffee/invites", json={"email": "theirs@test.local"},
                       headers=provider["auth"]).get_json()["invite"]
    got = client.delete(f"/api/coffee/invites/{made['id']}",
                        headers=admin["auth"])
    assert got.status_code == 404


def test_a_guest_page_whose_host_is_gone(client, provider):
    """The host account is deleted between the invite going out and the
    guest clicking. The link should say so rather than 500."""
    from core import database as db

    made = client.post("/api/coffee/invites", json={"email": "orphan@test.local"},
                       headers=provider["auth"]).get_json()["invite"]
    # Deleting the user cascades the invite away with it, which is a
    # different case entirely. The state this branch is written for is an
    # invite whose host row is gone, so the foreign key is relaxed for the
    # one statement that produces it and restored immediately.
    conn = db.get_db()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (provider["id"],))
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    got = client.get(f"/api/coffee/public/{made['token']}")
    assert got.status_code == 404
    assert "no longer available" in got.get_json()["error"]


def test_declining_a_link_that_is_not_valid(client):
    got = client.post("/api/coffee/public/not-a-token/decline", json={})
    assert got.status_code == 400
    assert "not valid" in got.get_json()["error"]


# ------------------------------------------------------------ appointments


def test_booking_a_slot_twice_is_a_conflict_not_a_crash(client, provider,
                                                        booking):
    """The unique index is what prevents it; this is the route turning that
    into something a client can read."""
    got = client.post("/api/appointments", headers=booking["auth"], json={
        "provider_id": provider["id"], "date": booking["date"],
        "start_time": booking["start"], "end_time": booking["end"]})
    assert got.status_code in (409, 400)
    assert "error" in got.get_json()


def test_cancelling_an_appointment_that_does_not_exist(client, booking):
    got = client.post("/api/appointments/999999/cancel",
                      headers=booking["auth"])
    assert got.status_code == 404
    assert "not found" in got.get_json()["error"].lower()


def test_a_stranger_may_not_touch_an_appointment(client, booking, provider):
    """Neither party, so neither the client nor the provider branch of the
    permission check applies."""
    from tests.conftest import register

    token, _user = register(client, "nosy@test.local")
    got = client.post(f"/api/appointments/{booking['id']}/cancel",
                      headers={"Authorization": f"Bearer {token}"})
    assert got.status_code in (403, 404)


# ----------------------------------------------------------- availability


def test_a_time_that_is_not_hh_mm_is_refused(client, provider):
    got = client.post("/api/availability/mine",
                      json={"day_of_week": 1, "start_time": "9am",
                            "end_time": "5pm", "slot_minutes": 30},
                      headers=provider["auth"])
    assert got.status_code == 400
    assert "HH:MM" in got.get_json()["error"]


# ------------------------------------------------------------- accounts


def test_an_admin_can_deactivate_somebody_else(client, admin, provider):
    """The guard is against deactivating *yourself*; the other branch had
    never run."""
    got = client.patch(f"/api/admin/users/{provider['id']}",
                       json={"is_active": False}, headers=admin["auth"])
    assert got.status_code == 200


def test_an_expired_token_says_so(client, app):
    """A separate sentence from "invalid": one means log in again, the other
    means something is wrong."""
    import jwt

    payload = {"sub": "1", "role": "client",
               "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)}
    stale = jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

    got = client.get("/api/appointments/mine",
                     headers={"Authorization": f"Bearer {stale}"})
    assert got.status_code == 401
    assert "expired" in got.get_json()["error"].lower()


# ------------------------------------------------------------ the 404 page


def test_an_unknown_api_path_answers_json(client):
    got = client.get("/api/nothing-here")
    assert got.status_code == 404
    assert got.get_json() == {"error": "Not found"}


def test_an_unknown_page_serves_the_app_shell(client):
    """A single-page app hands deep links back to the client router rather
    than 404-ing them into a JSON body the browser cannot render.

    It answers 200, not 404: render_template() alone carries no status, so
    the handler replaces the error rather than decorating it. That is the
    behaviour a deep link wants, and the assertion says so explicitly rather
    than leaving the next reader to wonder whether it is a bug.
    """
    got = client.get("/some/deep/link")
    assert got.status_code == 200
    assert b"<html" in got.data.lower()


# -------------------------------------------------------- the slot engine


def test_a_booking_that_does_not_land_on_the_grid_is_refused(ctx, provider):
    """is_slot_free walks the window in slot-sized steps. A duration that is
    not a multiple of the step would have its last slot finish past the end
    of the booking, so it is refused rather than half-held.

    The provider fixture runs a 15-minute grid, so 20 minutes is the
    smallest request that cannot be tiled.
    """
    from domain import calendar_logic

    day = dt.date.today() + dt.timedelta(days=5)
    while day.weekday() > 4:
        day += dt.timedelta(days=1)
    date_str = day.isoformat()

    assert calendar_logic.is_slot_free(provider["id"], date_str,
                                       "09:00", "09:15") is True
    assert calendar_logic.is_slot_free(provider["id"], date_str,
                                       "09:00", "09:20") is False, (
        "a 20-minute booking on a 15-minute grid would overrun its last slot")

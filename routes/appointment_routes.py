from flask import Blueprint, g, jsonify, request

from core import database as db
from notify import notifications
from accounts.auth import roles_required, token_required
from routes import camel_keys, is_date, is_hhmm
from domain.calendar_logic import is_slot_free

bp = Blueprint("appointment_routes", __name__, url_prefix="/api/appointments")


@bp.post("")
@token_required
@roles_required("client")
def book_appointment():
    data = request.get_json(silent=True) or {}
    try:
        provider_id = int(data["provider_id"])
        date_str = data["date"]
        start_time = data["start_time"]
        end_time = data["end_time"]
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "provider_id, date, start_time, end_time are required"}), 400
    notes = (data.get("notes") or "").strip() or None
    # Checked here because nothing below does: a date that is not a date
    # raised ValueError inside the slot engine and came back as a 500, and a
    # time that is not a string reached a `<` against one and did the same.
    if not is_date(date_str):
        return jsonify({"error": "date must be a real date in YYYY-MM-DD format"}), 400
    if not is_hhmm(start_time) or not is_hhmm(end_time):
        return jsonify({"error": "start_time and end_time must look like HH:MM"}), 400

    provider = db.query(
        "SELECT id FROM users WHERE id = ? AND role = 'provider' AND is_active = 1",
        (provider_id,),
        one=True,
    )
    if not provider:
        return jsonify({"error": "Provider not found"}), 404

    # The unique index only stops two bookings with the same *start*. Since
    # a booking may span several slots, 09:00-10:00 and 09:30-10:00 have
    # different starts and overlap, and two requests that both ran the free
    # check before either inserted would both have gone in. The write lock
    # makes the check and the insert one step, as pounds.create does.
    conn = db.lock_for_write("appointments")
    if not is_slot_free(provider_id, date_str, start_time, end_time):
        db.rollback(conn=conn)
        return jsonify({"error": "That slot is no longer available. Please pick another."}), 409

    try:
        new_id = db.insert(
            "INSERT INTO appointments (provider_id, client_id, date, start_time, end_time, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (provider_id, g.current_user["id"], date_str, start_time, end_time, notes),
            conn=conn,
        )
    except db.INTEGRITY_ERRORS:
        db.rollback()
        return jsonify(
            {"error": "That slot was just booked by someone else. Please pick another."}
        ), 409

    notifications.notify_booked(new_id)

    appt = db.query("SELECT * FROM appointments WHERE id = ?", (new_id,), one=True)
    return jsonify({"appointment": camel_keys(appt)}), 201


@bp.get("/mine")
@token_required
def my_appointments():
    role = g.current_user["role"]
    user_id = g.current_user["id"]

    if role == "client":
        rows = db.query(
            "SELECT a.*, u.name AS provider_name FROM appointments a "
            "JOIN users u ON u.id = a.provider_id "
            "WHERE a.client_id = ? ORDER BY a.date, a.start_time",
            (user_id,),
        )
    elif role == "provider":
        rows = db.query(
            "SELECT a.*, u.name AS client_name FROM appointments a "
            "JOIN users u ON u.id = a.client_id "
            "WHERE a.provider_id = ? ORDER BY a.date, a.start_time",
            (user_id,),
        )
    else:  # admin sees everything
        rows = db.query(
            "SELECT a.*, p.name AS provider_name, c.name AS client_name FROM appointments a "
            "JOIN users p ON p.id = a.provider_id "
            "JOIN users c ON c.id = a.client_id "
            "ORDER BY a.date DESC, a.start_time"
        )
    return jsonify({"appointments": camel_keys(rows)})


def _load(appt_id):
    return db.query("SELECT * FROM appointments WHERE id = ?", (appt_id,), one=True)


def _may_act_on(appt):
    """Both parties to an appointment may change it; an admin may change any.

    This used to be one function returning an appointment, or None, or the
    string "forbidden", which the callers then compared a dict against. Three
    kinds of thing out of one return is a sentinel pretending to be a type,
    and the caller cannot tell from the signature that it has to check for a
    magic string. Missing it fails open, which for a permission check is the
    wrong direction.
    """
    role, uid = g.current_user["role"], g.current_user["id"]
    if role == "admin":
        return True
    if role in ("client", "provider"):
        return appt[f"{role}_id"] == uid
    return False


def _change_status(appt_id, new_status, refusal, then_notify):
    """Move a confirmed appointment to `new_status`, once.

    Cancel and complete were two copies of the same load-check-update. They
    also shared a race: the status was read, then written unconditionally,
    so a cancel and a complete arriving together could both pass the
    "still confirmed" check, both write, and both send their email -- a
    client told the appointment was cancelled *and* thanked for coming. The
    UPDATE is now its own compare-and-swap: it only moves a row that is
    still confirmed, and whoever loses is told so and mails nobody.
    """
    appt = _load(appt_id)
    if not appt:
        return jsonify({"error": "Appointment not found"}), 404
    if not _may_act_on(appt):
        return jsonify({"error": refusal}), 403
    if appt["status"] != "confirmed":
        return jsonify({"error": f"Appointment is already {appt['status']}"}), 400

    moved = db.execute_rowcount(
        "UPDATE appointments SET status = ? WHERE id = ? AND status = 'confirmed'",
        (new_status, appt_id))
    if not moved:
        now = _load(appt_id)
        return jsonify({"error": f"Appointment is already {now['status']}"}), 409
    then_notify()
    return jsonify({new_status: True})


@bp.post("/<int:appt_id>/cancel")
@token_required
def cancel_appointment(appt_id):
    return _change_status(
        appt_id, "cancelled", "You can't cancel someone else's appointment",
        lambda: notifications.notify_cancelled(appt_id, cancelled_by=g.current_user))


@bp.post("/<int:appt_id>/complete")
@token_required
@roles_required("provider", "admin")
def complete_appointment(appt_id):
    return _change_status(
        appt_id, "completed", "You can't update someone else's appointment",
        lambda: notifications.notify_completed(appt_id))

"""
routes/schedule_routes.py
--------------------------
The imported timetable's HTTP surface.

Every endpoint is the caller's own timetable. `g.current_user["id"]` is the
only user id any handler here uses -- none reads one from the payload, which
is the shape that lets somebody edit another account's rows by guessing an
integer.

Import takes the planner's export as a JSON body rather than a file upload.
The planner already downloads exactly that object, and a multipart parser
here would exist only to unwrap it again; the browser reads the file and
posts its contents.
"""

from flask import Blueprint, g, jsonify, request

from domain import schedule
from accounts.auth import token_required
from routes import camel_keys
from domain.schedule import ScheduleError

bp = Blueprint("schedule_routes", __name__, url_prefix="/api")


def _fail(exc, code=400):
    return jsonify({"error": str(exc)}), code


@bp.get("/schedule")
@token_required
def my_schedule():
    """Everything imported, with the upcoming ones marked.

    `upcoming` is computed here rather than left to the page, so the list
    and any count of it cannot disagree about where "now" is.
    """
    rows = [schedule.view(row)
            for row in schedule.list_for_user(g.current_user["id"])]
    upcoming = [row["id"] for row in schedule.list_for_user(
        g.current_user["id"], upcoming_only=True)]
    return jsonify(camel_keys({
        "events": rows,
        "count": len(rows),
        "upcoming_count": len(upcoming),
        "reminds_before_minutes": _lead(),
    }))


@bp.post("/schedule/import")
@token_required
def import_planner():
    try:
        result = schedule.import_payload(g.current_user["id"],
                                         request.get_json(silent=True))
    except ScheduleError as exc:
        return _fail(exc)
    return jsonify(camel_keys({
        "imported": result,
        "events": [schedule.view(row)
                   for row in schedule.list_for_user(g.current_user["id"])],
    })), 201


@bp.delete("/schedule/<int:event_id>")
@token_required
def remove_event(event_id):
    try:
        schedule.delete(event_id, g.current_user["id"])
    except ScheduleError as exc:
        return _fail(exc, 404)
    return jsonify({"deleted": event_id})


@bp.delete("/schedule")
@token_required
def clear_schedule():
    """Drop the lot. The planner is the source of truth, so starting again
    from a fresh export is a normal thing to want."""
    return jsonify({"deleted": schedule.clear(g.current_user["id"])})


def _lead():
    from flask import current_app
    return int(current_app.config["IMMINENT_MINUTES_BEFORE"])

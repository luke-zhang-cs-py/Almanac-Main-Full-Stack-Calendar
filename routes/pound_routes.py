"""
routes/pound_routes.py
-----------------------
The pound wallet's HTTP surface.

Every endpoint here is the caller's own ledger and nothing else. There is no
provider/admin tier: a conversion belongs to the user who recorded it, the
limit is theirs, and `g.current_user["id"]` is the only user id any of these
handlers will use -- none of them reads one out of the payload, which is the
shape that lets a client edit somebody else's row by guessing an integer.

`quote` is a GET with no side effect on purpose. It is what the page calls
while somebody is typing an amount, so it must be safe to call on every
keystroke and must not care whether the limit has room.
"""

from flask import Blueprint, g, jsonify, request

from domain import pounds
from accounts.auth import token_required
from domain.pounds import PoundError
from routes import camel_keys

bp = Blueprint("pound_routes", __name__, url_prefix="/api")


def _fail(exc, code=400):
    return jsonify({"error": str(exc)}), code


# --------------------------------------------------------------- the ledger


@bp.get("/pounds")
@token_required
def my_conversions():
    """Everything the caller has converted, with the totals and the limit."""
    return jsonify(camel_keys(pounds.summary(g.current_user["id"])))


@bp.post("/pounds")
@token_required
def record_conversion():
    """Record one. Refused if it would carry the total past the limit."""
    try:
        draft = pounds.ConversionDraft.from_payload(request.get_json(silent=True))
        new_id = pounds.create(g.current_user["id"], draft)
    except PoundError as exc:
        return _fail(exc)
    return jsonify({"conversion": camel_keys(pounds.view(pounds.get(new_id))),
                    "summary": camel_keys(
                        pounds.summary(g.current_user["id"]))}), 201


@bp.delete("/pounds/<int:conversion_id>")
@token_required
def remove_conversion(conversion_id):
    try:
        pounds.delete(conversion_id, g.current_user["id"])
    except PoundError as exc:
        return _fail(exc, 404)
    return jsonify({"deleted": conversion_id,
                    "summary": camel_keys(pounds.summary(g.current_user["id"]))})


# ---------------------------------------------------------------- the quote


@bp.get("/pounds/quote")
@token_required
def quote():
    """What an amount would come to, without recording it.

    Answers whether it fits as well as what it costs, because the page needs
    to say "that would put you over" before the button is pressed rather
    than after the request is refused.
    """
    try:
        cad_cents = int(request.args.get("cadCents") or 0)
    except (TypeError, ValueError):
        return _fail(PoundError("The amount must be a whole number of cents."))
    if cad_cents <= 0:
        return _fail(PoundError("A conversion needs an amount."))

    on = request.args.get("on") or ""
    try:
        got = pounds.quote(cad_cents, on)
    except PoundError as exc:
        return _fail(exc)

    left = pounds.remaining(g.current_user["id"])
    got["fits"] = got["pence"] <= left
    got["remaining_pence"] = left
    got["pounds"] = pounds.money(got["pence"])
    got["fee"] = pounds.money(got["fee_pence"])
    got["reference"] = pounds.money(got["reference_pence"])
    return jsonify({"quote": camel_keys(got)})

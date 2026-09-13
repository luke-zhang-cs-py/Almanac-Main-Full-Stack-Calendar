"""
pounds.py
----------
Canadian dollars into pounds, against a 1,000 ceiling.

A provider here prices in Canadian dollars -- `offerings.price_cents` with a
`currency` that defaults to CAD -- and somebody spending those dollars in
Britain has a second question the catalogue cannot answer: what is this
actually costing me, and how much of my budget is left. This is that ledger.
It is per user, it converts at the rate published on the day the money was
spent, and it stops at a limit.

Where the rate comes from
-------------------------
The European Central Bank publishes against the euro, so there is no CAD-GBP
line to look up anywhere. There is EUR->CAD and EUR->GBP on the same day, and
the euro cancels:

    CAD per GBP = (EUR->CAD) / (EUR->GBP)

Both legs must come from the same published day. They almost always do -- the
ECB publishes every currency together -- but "almost always" is how a cross
rate nobody ever quoted ends up in a total, so it is checked rather than
assumed. `rates/eur_legs.csv` holds both legs for every business day since
1999; `tools/refresh_pound_rates.py` rewrites it from the ECB's own history.

The ECB publishes on business days only. A Sunday purchase is converted at
Friday's rate and the row says so, because the alternative -- reaching
forward to Monday -- makes a closed month's total change every time the file
is refreshed. A date later than the newest rate is refused on a weekday,
where a rate is still coming, and allowed at a weekend, where one is not.

Why the markup divides
----------------------
CIBC converts and *then* adds 2.5% to the Canadian figure. Buying pounds with
dollars is that same rule solved for the other unknown: to end up holding P
pounds you are charged

    C = P x (CAD per GBP) x 1.025

so a fixed C buys C / ((CAD per GBP) x 1.025). Multiplying the pounds by
0.975 instead is the tempting shortcut and it is a different number --
converting CA$1,000 at 1.87179 the shortcut says 520.89 and the right answer
is 521.22. `tests/test_pounds.py` pins the direction by round-tripping.

Why nothing stores a pound figure
---------------------------------
`pound_conversions` stores the dollars and the date. The pounds are derived,
and derived values that get stored drift: refresh the rate file and a stored
figure becomes a number no longer reachable from anything in the file. Every
pound figure here is computed on read, from the dollars and the rate history
this copy actually has.

Money is integer minor units throughout -- cents in, pence out -- which is
`offerings.py`'s rule for the same reason it gives, and the conversion is one
exact ratio of integers rounded once rather than a chain of decimals. See
`to_pounds`.
"""

import csv
import datetime as dt
import io
import logging
import os
import threading
from dataclasses import dataclass

import database as db

log = logging.getLogger(__name__)

# The ceiling, in pence. A budget, not a balance: recording a conversion that
# would carry the running total past it is refused, because a limit that only
# prints a warning is not a limit.
LIMIT_MINOR = 100000

# CIBC's published foreign currency conversion markup, in basis points.
CIBC_FEE_BP = 250
BASIS_POINTS = 10000

FROM = "CAD"
TO = "GBP"

# How far back to walk for a published rate. The longest gap in the ECB
# series is five days (Easter); ten leaves room without reaching into a
# fortnight-old rate and calling it the day's.
MAX_LOOKBACK_DAYS = 10

# Decimal places on the cross rate that gets shown. Display only -- nothing
# is computed from it.
RATE_PLACES = 6

DATE_FORMAT = "%Y-%m-%d"

RATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "rates", "eur_legs.csv")

_lock = threading.Lock()
_rates = None           # {date: {"CAD": (num, scale), "GBP": (num, scale)}}
_newest = None


class PoundError(Exception):
    """Something the caller can fix: a bad amount, a date with no rate, a
    conversion that would break the limit."""


# --------------------------------------------------------------- the rates


def _parts(text):
    """(integer numerator, decimal places) for an exact decimal string.

    "1.6064" -> (16064, 4). Keeping the rate as a pair of integers is what
    lets the conversion below stay in integers; see to_pounds.
    """
    text = str(text).strip()
    if not text:
        raise PoundError("empty rate")
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    if "." not in text:
        return sign * int(text), 0
    whole, _, frac = text.partition(".")
    return sign * int((whole or "0") + frac), len(frac)


def load(path=None, force=False):
    """The rate file, read once and kept.

    Read under a lock because the scheduler thread and a request thread can
    both arrive first, and two readers building the table at once would have
    one of them hand back a half-built dict.
    """
    global _rates, _newest
    with _lock:
        if _rates is not None and not force:
            return _rates

        table = {}
        with io.open(path or RATES_PATH, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                on = (row.get("date") or "").strip()
                if not on:
                    continue
                day = {}
                for code in (FROM, TO):
                    text = (row.get(code) or "").strip()
                    if text:
                        try:
                            day[code] = _parts(text)
                        except (PoundError, ValueError):
                            continue
                if day:
                    table[on] = day

        if not table:
            raise PoundError("the rate file has no rates in it")

        _rates = table
        _newest = max(table)
        return _rates


def reset():
    """Forget the loaded table. For tests, and after a refresh."""
    global _rates, _newest
    with _lock:
        _rates, _newest = None, None


def coverage():
    """What the shipped file covers, for a page that wants to say so."""
    table = load()
    days = sorted(table)
    return {"days": len(days), "oldest": days[0], "newest": days[-1]}


def _as_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.datetime.strptime(str(value).strip(), DATE_FORMAT).date()
    except ValueError:
        raise PoundError(f"{value!r} is not a date in YYYY-MM-DD form.")


def legs(on):
    """(CAD parts, GBP parts, the date both came from) for a spending date.

    Walks back to the most recent published business day. The returned date
    is not decoration -- it is what lets a row say which day's rate a weekend
    purchase was converted at.
    """
    table = load()
    on = _as_date(on)

    # Refused only if a rate for it could still arrive. A Saturday is later
    # than Friday's rate but its own is never coming, so refusing it would
    # leave weekend spending with no figure at all.
    if on.isoformat() > _newest and on.weekday() < 5:
        raise PoundError(
            f"{on.isoformat()} is later than the newest rate ({_newest}). "
            "Check the date, or refresh the rate file.")

    for back in range(MAX_LOOKBACK_DAYS + 1):
        day = (on - dt.timedelta(days=back)).isoformat()
        found = table.get(day)
        if found and FROM in found and TO in found:
            return found[FROM], found[TO], day

    raise PoundError(
        f"No published rate within {MAX_LOOKBACK_DAYS} days before "
        f"{on.isoformat()}.")


# ---------------------------------------------------------- the arithmetic


def div_half_up(numerator, denominator):
    """Integer division rounding half away from zero.

    Half away rather than banker's because it is what a person gets doing it
    by hand, and a column of figures that rounds 2.5 down and 3.5 up reads
    like a bug even where it is defensible.
    """
    if denominator <= 0:
        raise PoundError("cannot divide by that")
    if numerator >= 0:
        return (numerator * 2 + denominator) // (denominator * 2)
    return -((-numerator * 2 + denominator) // (denominator * 2))


def cross(cad, gbp, places=RATE_PLACES):
    """CAD per GBP as a string, for showing. Nothing converts with it."""
    cad_num, cad_scale = cad
    gbp_num, gbp_scale = gbp
    scaled = div_half_up(cad_num * 10 ** gbp_scale * 10 ** places,
                         gbp_num * 10 ** cad_scale)
    digits = str(abs(scaled)).rjust(places + 1, "0")
    return f"{digits[:-places]}.{digits[-places:]}"


def to_pounds(cad_cents, cad, gbp, fee_bp=CIBC_FEE_BP):
    """`cad_cents` Canadian cents as pence, via the euro, after the markup.

    One exact ratio of integers, rounded once:

        pence = cents x GBP_num x 10^CAD_scale x 10000
                ---------------------------------------
                CAD_num x 10^GBP_scale x (10000 + fee)

    Dividing the legs first to get a CAD-per-GBP decimal is the obvious
    shape and it is worse: the quotient does not terminate, so it has to be
    rounded somewhere, and then the figure depends on where. Every term here
    is a whole number.

    Returns the reference figure, what is actually left after the markup, and
    the difference -- all three, because the markup is the point and a single
    net number hides it.
    """
    cad_cents = abs(int(cad_cents))
    fee_bp = int(fee_bp)
    if fee_bp < 0:
        raise PoundError("A markup cannot be negative.")

    cad_num, cad_scale = cad
    gbp_num, gbp_scale = gbp
    if cad_num <= 0 or gbp_num <= 0:
        raise PoundError("Implausible published rate.")

    numerator = cad_cents * gbp_num * 10 ** cad_scale
    denominator = cad_num * 10 ** gbp_scale

    reference = div_half_up(numerator, denominator)
    pence = div_half_up(numerator * BASIS_POINTS,
                        denominator * (BASIS_POINTS + fee_bp))

    return {
        "cad_cents": cad_cents,
        "reference_pence": reference,
        "pence": pence,
        "fee_pence": reference - pence,
        "fee_bp": fee_bp,
        "cross": cross(cad, gbp),
    }


def from_pounds(pence, cad, gbp, fee_bp=CIBC_FEE_BP):
    """The dollars needed to end up holding `pence`.

    to_pounds solved for the other unknown, so "how much can I still
    convert" is computed rather than estimated by scaling the last answer.
    Rounding makes it a left inverse only to within a penny, which is what
    the test asserts rather than an exactness it does not have.
    """
    pence = abs(int(pence))
    fee_bp = int(fee_bp)
    if fee_bp < 0:
        raise PoundError("A markup cannot be negative.")

    cad_num, cad_scale = cad
    gbp_num, gbp_scale = gbp
    return div_half_up(
        pence * cad_num * 10 ** gbp_scale * (BASIS_POINTS + fee_bp),
        gbp_num * 10 ** cad_scale * BASIS_POINTS)


def quote(cad_cents, on, fee_bp=CIBC_FEE_BP):
    """What converting `cad_cents` on `on` would come to, without recording."""
    cad, gbp, rate_date = legs(on)
    out = to_pounds(cad_cents, cad, gbp, fee_bp)
    out["spent_on"] = _as_date(on).isoformat()
    out["rate_date"] = rate_date
    out["lag_days"] = (_as_date(on) - _as_date(rate_date)).days
    return out


def money(pence, currency=TO):
    """Render pence the way a person reads it.

    Deliberately not offerings.money: that one says "Free" for zero and drops
    trailing zeros, which is right for a price in a catalogue and wrong for a
    column of figures that has to line up. Zero pounds converted is "£0.00",
    not "Free".
    """
    symbol = {"CAD": "CA$", "USD": "US$", "GBP": "£", "EUR": "€"}.get(
        currency, "")
    sign = "-" if pence < 0 else ""
    whole, minor = divmod(abs(int(pence)), 100)
    return f"{sign}{symbol}{whole:,}.{minor:02d}"


# ------------------------------------------------------------- the ledger


@dataclass
class ConversionDraft:
    """One conversion before it has an id.

    The same shape offerings.OfferingDraft uses, for the same reason: the
    fields travel together, and from_payload is where the wire's camelCase
    stops and the domain's names start.
    """

    spent_on: str
    description: str
    cad_cents: int
    category: str = None

    @classmethod
    def from_payload(cls, body):
        body = body or {}
        try:
            return cls(
                spent_on=(body.get("spentOn") or "").strip(),
                description=(body.get("description") or "").strip(),
                cad_cents=int(body.get("cadCents") or 0),
                category=(body.get("category") or "").strip() or None,
            )
        except (TypeError, ValueError):
            raise PoundError("The amount must be a whole number of cents.")

    def validate(self):
        if not self.description:
            raise PoundError("Say what it was.")
        if self.cad_cents <= 0:
            raise PoundError("A conversion needs an amount.")
        # Raises if the date is unusable or has no rate behind it, so a row
        # is never stored that the ledger could not then convert.
        legs(self.spent_on)


def list_for_user(user_id, conn=None):
    return db.query(
        "SELECT * FROM pound_conversions WHERE user_id = ? "
        "ORDER BY spent_on DESC, id DESC", (user_id,), conn=conn)


def get(conversion_id, conn=None):
    return db.query("SELECT * FROM pound_conversions WHERE id = ?",
                    (conversion_id,), one=True, conn=conn)


def spent(user_id, conn=None):
    """The pounds actually received, totalled from the rows.

    Totalled from the converted rows rather than by converting the total:
    the page shows the rows, so the rows are what must be right, and a total
    that disagrees with the column above it is how a reader stops believing
    every other figure.
    """
    total = 0
    for row in list_for_user(user_id, conn=conn):
        try:
            total += quote(row["cad_cents"], row["spent_on"])["pence"]
        except PoundError:
            continue
    return total


def remaining(user_id, conn=None):
    """What is left of the limit. Negative is reported, not clamped -- a
    total that silently stops at zero is a total that lies."""
    return LIMIT_MINOR - spent(user_id, conn=conn)


def create(user_id, draft, conn=None):
    """Record a conversion. Returns the new id.

    Refuses one that would carry the running total past the limit, and says
    how much room is left rather than only that it failed, because "no"
    without a number is not something a caller can act on.
    """
    draft.validate()
    got = quote(draft.cad_cents, draft.spent_on)

    left = remaining(user_id, conn=conn)
    if got["pence"] > left:
        raise PoundError(
            f"That would take you past the {money(LIMIT_MINOR)} limit. "
            f"{money(left)} is left, which is about "
            f"{money(max(0, from_pounds(left, *legs(draft.spent_on)[:2])), FROM)}"
            f" at that day's rate.")

    return db.insert(
        """INSERT INTO pound_conversions
           (user_id, spent_on, description, category, cad_cents)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, draft.spent_on, draft.description, draft.category,
         int(draft.cad_cents)), conn=conn)


def delete(conversion_id, owner_id, conn=None):
    """Remove one of the caller's own conversions."""
    existing = get(conversion_id, conn=conn)
    if not existing or existing["user_id"] != owner_id:
        raise PoundError("Conversion not found.")
    db.execute("DELETE FROM pound_conversions WHERE id = ?", (conversion_id,),
               conn=conn)


# ---------------------------------------------------------------- the wire


def view(row):
    """One conversion, with its pounds worked out.

    The pounds are computed here rather than read from the row because they
    are not in the row -- see the note at the top about derived values.
    """
    out = {
        "id": row["id"],
        "spent_on": row["spent_on"],
        "description": row["description"],
        "category": row["category"],
        "cad_cents": row["cad_cents"],
        "cad": money(row["cad_cents"], FROM),
    }
    try:
        got = quote(row["cad_cents"], row["spent_on"])
    except PoundError as exc:
        out["error"] = str(exc)
        return out

    out.update({
        "pence": got["pence"],
        "pounds": money(got["pence"]),
        "fee_pence": got["fee_pence"],
        "fee": money(got["fee_pence"]),
        "rate_date": got["rate_date"],
        "lag_days": got["lag_days"],
        "cross": got["cross"],
    })
    return out


def summary(user_id, conn=None):
    """The whole view a page needs: the rows, the totals, and the limit."""
    rows = [view(row) for row in list_for_user(user_id, conn=conn)]
    used = sum(row.get("pence", 0) for row in rows)
    left = LIMIT_MINOR - used
    return {
        "conversions": rows,
        "limit_pence": LIMIT_MINOR,
        "spent_pence": used,
        "remaining_pence": left,
        "spent": money(used),
        "remaining": money(left),
        "limit": money(LIMIT_MINOR),
        "cad_total_cents": sum(row["cad_cents"] for row in rows),
        "cad_total": money(sum(row["cad_cents"] for row in rows), FROM),
        "over": left < 0,
        "fee_bp": CIBC_FEE_BP,
        "rates": coverage(),
    }

"""Build the browser-only slot-engine demo into docs/app/.

    python tools/build_static.py
    python tools/build_static.py --prove     (see "Proving it bites", below)

--------------------------------------------------------------------------
What this publishes, and what it refuses to pretend
--------------------------------------------------------------------------
Almanac is JWT sign-in over a relational database, transactional email
through a background queue, and a reminder thread that wakes up every
quarter of an hour. None of that runs in a browser tab, and a page that
mimed it -- a fake login, a fake inbox, rows kept in localStorage and called
a database -- would be a worse thing to publish than nothing, because the
one honest sentence about it would be the one nobody reads.

So this does not ship the platform. It ships the one part of the platform
that is pure computation and is also the part actually worth reading:

    domain/calendar_logic.py -- recurring weekly hours, minus one-off
    blocks, minus confirmed bookings, tiled into the slots a guest may
    book.

That module takes three tables in and gives a list of {start, end} out. It
has no clock beyond "now", no network, no state, and a surprising number of
edges: a date in the past, a day with nothing on it, a block that clips one
corner of one slot, a cancelled booking that frees its slot again, a block
with a start and no end, a slot_minutes of zero that would spin forever, a
booking longer than the grid the provider set. That is the demo.

  tools/static_src/js/slots.js    calendar_logic.py, ported
  tools/static_src/js/demo.js     the page: reads controls, draws the board
  tools/static_src/index.html     the markup, which the Flask app has no
                                  equivalent of -- see below
  tools/static_src/css/demo.css   the banner and the two-column layout

`static/css/style.css` is copied from the Flask app byte for byte, so the
page is the same departure board in the same colours as the real one.

The page's *markup* is this build's own rather than a copy of
`templates/index.html`, and that is worth saying plainly: the Flask app has
no "slot engine" page to copy. Its template is an SPA shell whose first
screen is a sign-in form. Copying it would mean copying the thing this
build refuses to fake. What must not be allowed to rot is the engine, and
the engine is not copied either -- it is ported, and then checked.

The scenarios are inlined as `js/scenarios.js` rather than fetched as
`.json`, deliberately: a `fetch()` of a relative URL is blocked by the
file:// origin rules, so a JSON bundle would work on GitHub Pages and fail
the moment somebody double-clicked index.html. A `<script src>` has no such
restriction, so the same directory works both ways.

--------------------------------------------------------------------------
What this refuses to ship
--------------------------------------------------------------------------
A slot list that is *nearly* right is the worst possible output of this
program. Every failure mode is quiet: a day that offers one slot too many
looks exactly like a day that offers the right number, and the way you find
out is that two people are booked into the same half hour. The published
page is the copy most people will ever see, and no test in tests/ runs it.

So the port is not trusted. Before a byte is written, this script starts a
real browser, loads the JavaScript it is about to publish, and compares it
against the real Python -- the real Python, running its real SQL against a
real SQLite database, through `core.database`, inside a real Flask app
context -- over a matrix of scenarios covering:

  * varying opening hours: one window, two windows a day, overlapping
    windows, windows that do not divide evenly by the slot length, a window
    ending at "24:00", a weekday with no window at all, and no hours at all
    anywhere;
  * slot lengths of 7, 30, 45, 60, 90 and 360 minutes, and the stored rows
    that must not be tiled at all: zero and negative, either of which
    would advance the cursor by nothing and append slots until the tab
    ran out of memory. A NULL slot length is not in the matrix because
    the column is NOT NULL and the database refuses to hold one;
  * blocks: a whole day off (both times NULL), a block with a start and no
    end, a NULL start with an end, two blocks that overlap each other, a
    block that covers ten minutes in the middle of one slot, a block that
    straddles the boundary between two, and a block nobody can parse;
  * existing bookings: the status filter is `= 'confirmed'`, so a
    confirmed one takes its slot out and a cancelled *or* completed one
    leaves it free -- which for a completed appointment is almost always
    moot, because it is in the past, and is still the behaviour a port
    that widened the filter to "not cancelled" would change. All three
    statuses are in the matrix, plus a day booked solid end to end, plus a
    booking whose stored time is unreadable -- which the Python
    deliberately does *not* catch, so the port must not catch it either;
  * days with nothing on them, from three different causes;
  * DST-adjacent dates -- 8 March and 1 November (US), 29 March and 25
    October (EU) -- including a "now" of 02:30 on a spring-forward morning,
    a wall-clock time that does not exist in several timezones. The engine
    has no timezone anywhere in it and these must be ordinary Sundays; the
    scenarios are here so that a port that reached for `new Date()` and
    acquired one is caught rather than trusted;
  * a date in the past, both yesterday and six years ago, and today with
    the morning already gone, and a slot starting at the exact minute of
    "now", which is not bookable;
  * a fully booked day;
  * two providers whose rows sit on the same dates, so a port that dropped
    a `provider_id` filter is caught;
  * dates that are not dates -- 2026-02-30, 2026-13-01, an unpadded
    2026-9-5 that is legal, a trailing space that is not -- where what is
    compared is that both sides refused;
  * `is_slot_free` over spans of one slot, several slots, a span that
    crosses a busy gap, one that overruns the end of the day, and one that
    does not start on the grid;
  * `slot_starts_for` at 0, 1, 7, 30, 45, 60, 90, 120, 180, 360, 720, 900,
    1440 and 1441 minutes, and at -1 and -30, where the end time formats
    with a minus sign in it and the two sides have to agree on that
    before they can agree about whether it fits.

Every produced list is compared element by element and field by field.
Any disagreement stops the build. Nothing is written.

--------------------------------------------------------------------------
Proving it bites
--------------------------------------------------------------------------
A comparison that cannot fail is worse than no comparison, because it reads
like one that passed. `--prove` is the standing answer to that: it breaks
the published bundle on purpose, twelve ways, and requires the checks to
catch every one.

    past-date        stop treating a past date as entirely past
    exact-now        offer the slot starting this very minute
    overlap          require a busy range to contain a slot, not clip it
    whole-day        read a NULL/NULL block as zero length
    open-end         read a start with no end as zero length
    cancelled        treat every non-cancelled appointment as busy
    provider         drop the provider_id filter on blocks and bookings
    span-offgrid     accept a span that does not start on a free slot
    span-exact       stop requiring a span to end on a slot boundary
    weekday          shift every weekday by one
    format           stop zero-padding the hour
    unsorted         hand the slots back in window order

Each is injected into the *published* slots.js, so it is the real bundle
being broken rather than a mock of it. If any sabotage survives, `--prove`
fails and says which -- that is a hole in the matrix, and it is reported as
a build failure rather than as a passing run.

It has already been useful, and not in the direction expected. The first
list had a thirteenth entry: delete `is_slot_free`'s early `if following >
end_time: return False`, which reads like the guard that stops a booking
running past the end of the day. It survived all 363 comparisons, and it
should have: the cursor only ever moves forward along the chain of slot
boundaries, so once it has passed the requested end it can never come back
to it, and the closing `cursor == end_time` returns False either way. That
line is an early exit and a statement of intent, not a behaviour. A
sabotage list that had kept it would have been claiming coverage of a
branch that has no other side -- so it was replaced by two that do change
the answer, and this paragraph is here instead.

The browser is the system Chrome if it is there and Playwright's Chromium
otherwise. That is a build-time dependency, not a runtime one: `pip install
-r requirements.txt` and `pytest` do not need it, and neither does the
published page. Running the JavaScript rather than transcribing it a third
time is the point -- a transcription of a port is just a third thing to get
wrong.
"""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "docs", "app")
SRC = os.path.join(ROOT, "tools", "static_src")

REPO = ("https://github.com/luke-zhang-cs-py/Almanac-Main-Full-Stack-Calendar")

# Where Chrome lives on the machine this is developed on. Optional:
# Playwright ships its own Chromium and that is used when this is not here,
# so the build works on a runner too.
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

BANNER = "/* Generated by tools/build_static.py -- edit %s instead. */\n"

# The two providers in every scenario. 1 is the subject; 2 exists so that a
# port which forgot a provider_id filter has somebody else's calendar to
# leak.
SUBJECT = 1
OTHER = 2

# What each side is allowed to raise and still be called "it refused".
# Anything outside these is a bug in that side, not a refusal, and is
# reported as a difference.
PY_REFUSALS = ("ValueError", "AttributeError")
JS_REFUSALS = ("DateError", "TimeError")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def stop(message):
    raise SystemExit("build_static: " + message)


# ---------------------------------------------------------------------------
# The scenarios
# ---------------------------------------------------------------------------
# Chosen, not random. Each one exists because there is a specific way for a
# port to be wrong that nothing else here would notice.
#
# Rows are written in the shape of the tables they go into, because that is
# what both sides read: the Python inserts them into SQLite and lets
# calendar_logic's own SQL find them again, and the JavaScript filters the
# same arrays with the same WHERE clauses restated.
#
# hours:    (provider_id, day_of_week, start_time, end_time, slot_minutes)
#           day_of_week is Sunday = 0, which is what the table stores.
# blocks:   (provider_id, date, start_time, end_time)
# booked:   (provider_id, date, start_time, end_time, status)

WEEK = "2026-09"                       # the reference week: 14th is a Monday
MON, TUE, WED, THU, FRI, SAT, SUN = (
    WEEK + "-14", WEEK + "-15", WEEK + "-16", WEEK + "-17", WEEK + "-18",
    WEEK + "-19", WEEK + "-13")
NEXT_WED = WEEK + "-23"

NOW = "2026-09-16T10:30"               # a Wednesday, mid-morning


def nine_to_five(provider=SUBJECT, slot=30):
    """Monday to Friday, the ordinary case."""
    return [(provider, day, "09:00", "17:00", slot) for day in range(1, 6)]


def ask(date, provider=SUBJECT):
    return {"provider": provider, "date": date}


def probe(date, start, end, provider=SUBJECT):
    return {"provider": provider, "date": date, "start": start, "end": end}


def scenario(name, note, hours, blocks=(), booked=(), asks=(), durations=(),
             probes=(), now=NOW, demo=False, day=3, date=None, duration=0):
    return {
        "name": name,
        "note": note,
        "now": now,
        "demo": demo,
        # Only read when demo is true: what the page should open on.
        "day": day,
        "date": date or (asks[0]["date"] if asks else WED),
        "duration": duration,
        "data": {
            "availability": [
                {"provider_id": p, "day_of_week": d, "start_time": s,
                 "end_time": e, "slot_minutes": m}
                for p, d, s, e, m in hours],
            "blocked_slots": [
                {"provider_id": p, "date": d, "start_time": s, "end_time": e}
                for p, d, s, e in blocks],
            "appointments": [
                {"provider_id": p, "date": d, "start_time": s, "end_time": e,
                 "status": k}
                for p, d, s, e, k in booked],
        },
        "asks": list(asks),
        "durations": list(durations),
        "probes": list(probes),
    }


def scenarios():
    out = []

    out.append(scenario(
        "A full week, nine to five",
        "Monday to Friday, 09:00 to 17:00, half-hour slots, and nothing in "
        "the way. The Saturday and the Sunday have no hours at all, "
        "yesterday is in the past, and today is half gone.",
        hours=nine_to_five(),
        asks=[ask(SUN), ask(MON), ask(TUE), ask(WED), ask(THU), ask(SAT)],
        durations=[0, 30, 60, 90, 120],
        probes=[probe(THU, "09:00", "09:30"), probe(THU, "09:00", "10:00"),
                probe(THU, "09:00", "11:00"), probe(THU, "09:15", "09:45"),
                probe(THU, "16:30", "17:30"), probe(THU, "17:00", "17:30"),
                probe(WED, "09:00", "10:00"), probe(WED, "11:00", "11:30"),
                probe(SAT, "09:00", "09:30"), probe(TUE, "09:00", "09:30")],
        demo=True, day=4, date=THU, duration=60))

    out.append(scenario(
        "A long way in the past",
        "Six years ago, on a weekday the provider works. A date strictly "
        "before today is entirely in the past, so there is nothing left on "
        "it -- not the afternoon, not anything.",
        hours=nine_to_five(),
        asks=[ask("2020-01-15"), ask("2020-01-18"), ask(TUE)],
        durations=[0, 60],
        probes=[probe("2020-01-15", "09:00", "10:00")]))

    out.append(scenario(
        "Two windows, a block and a booking",
        "Mornings and afternoons with a gap for lunch, an hour blocked out "
        "mid-morning, one confirmed appointment, one cancelled and one "
        "completed. Only the confirmed one is busy: the filter is "
        "status = 'confirmed', so cancelled and completed both leave "
        "their slot free.",
        hours=[(SUBJECT, d, "08:00", "12:00", 60) for d in range(1, 6)] +
              [(SUBJECT, d, "13:00", "17:00", 60) for d in range(1, 6)],
        blocks=[(SUBJECT, THU, "10:00", "11:00")],
        booked=[(SUBJECT, THU, "14:00", "15:00", "confirmed"),
                (SUBJECT, THU, "15:00", "16:00", "cancelled"),
                (SUBJECT, THU, "16:00", "17:00", "completed")],
        asks=[ask(THU), ask(FRI)],
        durations=[0, 60, 120, 180],
        probes=[probe(THU, "08:00", "10:00"), probe(THU, "09:00", "11:00"),
                probe(THU, "13:00", "15:00"), probe(THU, "15:00", "16:00"),
                probe(THU, "15:00", "17:00")],
        demo=True, day=4, date=THU, duration=60))

    out.append(scenario(
        "A block that only clips a slot",
        "Ten minutes blocked in the middle of one half-hour slot, and "
        "another ten straddling the boundary between two. Any overlap at "
        "all takes the slot out -- the two ways to be wrong here are not "
        "equal, and double-booking is the one this exists to prevent.",
        hours=[(SUBJECT, 3, "09:00", "12:00", 30)],
        blocks=[(SUBJECT, NEXT_WED, "09:40", "09:50"),
                (SUBJECT, NEXT_WED, "10:55", "11:05")],
        asks=[ask(NEXT_WED)],
        durations=[0, 30, 60],
        probes=[probe(NEXT_WED, "09:30", "10:00"),
                probe(NEXT_WED, "10:00", "11:00"),
                probe(NEXT_WED, "11:30", "12:00")],
        demo=True, day=3, date=NEXT_WED, duration=0))

    out.append(scenario(
        "Blocks that overlap each other",
        "Three blocks on one date, two of them overlapping, one of them "
        "inside a third. They are not merged and they do not need to be: a "
        "slot is dropped if it overlaps any of them.",
        hours=[(SUBJECT, 3, "09:00", "17:00", 30)],
        blocks=[(SUBJECT, NEXT_WED, "10:00", "12:00"),
                (SUBJECT, NEXT_WED, "11:00", "13:00"),
                (SUBJECT, NEXT_WED, "11:15", "11:30"),
                (SUBJECT, NEXT_WED, "16:00", "16:00")],
        asks=[ask(NEXT_WED)],
        durations=[0, 30, 90],
        probes=[probe(NEXT_WED, "09:00", "10:00"),
                probe(NEXT_WED, "13:00", "14:00"),
                probe(NEXT_WED, "09:30", "13:30")]))

    out.append(scenario(
        "A whole day off",
        "One blocked_slots row with both times empty. That is the "
        "documented way to take a day off, and it means the whole day.",
        hours=[(SUBJECT, 3, "09:00", "17:00", 30)],
        blocks=[(SUBJECT, NEXT_WED, None, None)],
        asks=[ask(NEXT_WED), ask(THU)],
        durations=[0, 60],
        probes=[probe(NEXT_WED, "09:00", "09:30")],
        demo=True, day=3, date=NEXT_WED, duration=0))

    out.append(scenario(
        "Blocked from two o'clock",
        "A start with no end. \"Blocked from 14:00\" is the natural reading "
        "of that row and the only one that cannot double-book, so it runs "
        "to the end of the day.",
        hours=[(SUBJECT, 3, "09:00", "17:00", 60)],
        blocks=[(SUBJECT, NEXT_WED, "14:00", None)],
        asks=[ask(NEXT_WED)],
        durations=[0, 60, 120],
        probes=[probe(NEXT_WED, "13:00", "14:00"),
                probe(NEXT_WED, "13:00", "15:00")],
        demo=True, day=3, date=NEXT_WED, duration=0))

    out.append(scenario(
        "A null start with an end",
        "A row the API now refuses to create and used to accept. A start of "
        "NULL is read as the whole day whatever the end says -- the safe "
        "way round, because a block nobody can interpret should not quietly "
        "disappear.",
        hours=[(SUBJECT, 3, "09:00", "17:00", 60)],
        blocks=[(SUBJECT, NEXT_WED, None, "10:00")],
        asks=[ask(NEXT_WED)],
        durations=[0, 60]))

    out.append(scenario(
        "Rows nobody can read",
        "Stored garbage, of every kind the two modules guard against: a "
        "block whose times are not times, an availability window whose "
        "start is empty, a slot length of zero and a negative one -- each "
        "of which would tile forever -- and a window that ends before it "
        "starts. A NULL slot length is not here because the column is NOT "
        "NULL and the database refuses it, which is the right place for "
        "that to be refused.",
        hours=[(SUBJECT, 3, "", "17:00", 30),
               (SUBJECT, 3, "09:00", "nope", 30),
               (SUBJECT, 3, "09:00", "17:00", 0),
               (SUBJECT, 3, "09:00", "17:00", -30),
               (SUBJECT, 3, "16:00", "09:00", 30),
               (SUBJECT, 3, "14:00", "15:00", 30)],
        blocks=[(SUBJECT, NEXT_WED, "not-a-time", "10:00"),
                (SUBJECT, NEXT_WED, "25:ab", "26:00")],
        asks=[ask(NEXT_WED)],
        durations=[0, 30]))

    out.append(scenario(
        "Unreadable rows, without the blocks",
        "The same broken windows with nothing blocked, so what the tiler "
        "skips is visible on its own rather than behind a whole-day block.",
        hours=[(SUBJECT, 3, "9:5", "17:00", 45),
               (SUBJECT, 3, "09:00", "09:00", 30),
               (SUBJECT, 3, " 09:00 ", "10:00", 30),
               (SUBJECT, 3, "+9:+30", "10:00", 30)],
        asks=[ask(NEXT_WED)],
        durations=[0, 45]))

    out.append(scenario(
        "A day booked solid",
        "Three hour-long slots and three confirmed appointments. Nothing "
        "left, which is a different empty answer from a day with no hours "
        "and from a day in the past, and all three have to come back the "
        "same way: an empty list.",
        hours=[(SUBJECT, 5, "09:00", "12:00", 60)],
        booked=[(SUBJECT, FRI, "09:00", "10:00", "confirmed"),
                (SUBJECT, FRI, "10:00", "11:00", "confirmed"),
                (SUBJECT, FRI, "11:00", "12:00", "confirmed")],
        asks=[ask(FRI)],
        durations=[0, 60],
        probes=[probe(FRI, "09:00", "10:00")],
        demo=True, day=5, date=FRI, duration=0))

    out.append(scenario(
        "Two providers on the same dates",
        "Both work Wednesdays; each has the other's blocks and bookings "
        "sitting beside their own in the same three tables. Neither may see "
        "them.",
        hours=[(SUBJECT, 3, "09:00", "12:00", 60),
               (OTHER, 3, "09:00", "12:00", 60)],
        blocks=[(OTHER, NEXT_WED, "09:00", "10:00"),
                (SUBJECT, NEXT_WED, "11:00", "12:00")],
        booked=[(OTHER, NEXT_WED, "10:00", "11:00", "confirmed")],
        asks=[ask(NEXT_WED), ask(NEXT_WED, OTHER)],
        durations=[0, 60],
        probes=[probe(NEXT_WED, "09:00", "10:00"),
                probe(NEXT_WED, "09:00", "10:00", OTHER),
                probe(NEXT_WED, "10:00", "11:00", OTHER)]))

    out.append(scenario(
        "Today, with the morning gone",
        "Now is 10:30 on this Wednesday. Every slot at or before 10:30 has "
        "started -- including the one starting at exactly 10:30, because by "
        "the time anybody confirmed it, it would have begun.",
        hours=[(SUBJECT, 3, "09:00", "13:00", 30)],
        asks=[ask(WED)],
        durations=[0, 30, 60],
        probes=[probe(WED, "10:00", "10:30"), probe(WED, "10:30", "11:00"),
                probe(WED, "11:00", "11:30")],
        now="2026-09-16T10:30",
        demo=True, day=3, date=WED, duration=0))

    out.append(scenario(
        "Now, at the first minute of the day",
        "A window starting at midnight and a now of midnight. The 00:00 "
        "slot is already gone by the same rule.",
        hours=[(SUBJECT, 3, "00:00", "24:00", 360)],
        asks=[ask(WED), ask(NEXT_WED)],
        durations=[0, 360, 720, 1440],
        probes=[probe(NEXT_WED, "00:00", "06:00"),
                probe(NEXT_WED, "00:00", "24:00"),
                probe(NEXT_WED, "18:00", "24:00")],
        now="2026-09-16T00:00"))

    out.append(scenario(
        "The clocks go forward and back",
        "Four DST-adjacent Sundays -- 8 March and 1 November in the US, 29 "
        "March and 25 October in Europe -- and a now of 02:30 on a "
        "spring-forward morning, a wall-clock time that does not exist in "
        "several timezones. There is no timezone anywhere in this engine "
        "and these are ordinary Sundays. A port that reached for a Date "
        "object to work out the weekday would find out here.",
        hours=[(SUBJECT, 0, "09:00", "17:00", 60),
               (SUBJECT, 1, "09:00", "17:00", 60)],
        blocks=[(SUBJECT, "2026-03-29", "12:00", "13:00")],
        booked=[(SUBJECT, "2026-11-01", "10:00", "11:00", "confirmed")],
        asks=[ask("2026-03-08"), ask("2026-03-09"), ask("2026-03-29"),
              ask("2026-10-25"), ask("2026-11-01"), ask("2026-11-02")],
        durations=[0, 60, 120],
        probes=[probe("2026-03-08", "09:00", "11:00"),
                probe("2026-11-01", "09:00", "11:00")],
        now="2026-03-08T02:30"))

    out.append(scenario(
        "A leap day, and four dates that are not dates",
        "29 February 2028 exists and 29 February 2026 does not. Neither "
        "does the 30th of February or the 13th month. 2026-9-5 unpadded is "
        "legal and the same date with a trailing space is not. What is "
        "compared for the refusals is that both sides refused.",
        hours=[(SUBJECT, day, "09:00", "11:00", 60) for day in range(7)],
        asks=[ask("2028-02-29"), ask("2026-02-29"), ask("2026-02-30"),
              ask("2026-13-01"), ask("2026-00-10"), ask("2026-9-5"),
              ask("2026-09-05 "), ask("20260905"), ask("nonsense"),
              ask(""), ask("2026-09-05T00:00")],
        durations=[0, 60],
        probes=[probe("2028-02-29", "09:00", "10:00"),
                probe("2026-02-30", "09:00", "10:00")],
        now="2026-01-01T00:00"))

    out.append(scenario(
        "Slot lengths that do not divide the day",
        "Forty-five minutes into an eight-hour day leaves a stub at the "
        "end; seven minutes into fifty leaves one minute; a window that "
        "ends at 24:00 has to tile up to it and stop.",
        hours=[(SUBJECT, 1, "09:00", "17:00", 45),
               (SUBJECT, 2, "09:00", "09:50", 7),
               (SUBJECT, 4, "23:00", "24:00", 30),
               (SUBJECT, 5, "09:00", "10:00", 90)],
        asks=[ask("2026-09-21"), ask("2026-09-22"), ask("2026-09-24"),
              ask("2026-09-25")],
        durations=[0, 7, 45, 90],
        probes=[probe("2026-09-24", "23:00", "24:00"),
                probe("2026-09-24", "23:30", "24:00"),
                probe("2026-09-22", "09:00", "09:14")]))

    out.append(scenario(
        "Two windows that overlap each other",
        "A provider may store overlapping hours, and nothing merges them. "
        "The same start can come out of both, and the sort has to be stable "
        "about it.",
        hours=[(SUBJECT, 3, "09:00", "12:00", 60),
               (SUBJECT, 3, "10:00", "13:00", 60)],
        blocks=[(SUBJECT, NEXT_WED, "11:00", "11:30")],
        asks=[ask(NEXT_WED)],
        durations=[0, 60, 120],
        probes=[probe(NEXT_WED, "09:00", "11:00"),
                probe(NEXT_WED, "12:00", "13:00")]))

    out.append(scenario(
        "Durations nobody should ask for",
        "Zero, negative, and longer than a day. slot_starts_for adds the "
        "duration to a start and formats the result, which for a negative "
        "one is a time with a minus in it -- so the two sides have to "
        "format it the same way before they can disagree about whether it "
        "fits.",
        hours=[(SUBJECT, 3, "09:00", "12:00", 30)],
        asks=[ask(NEXT_WED)],
        durations=[0, -30, -1, 1, 1440, 1441, 900],
        probes=[probe(NEXT_WED, "09:00", "09:00"),
                probe(NEXT_WED, "10:00", "09:00")]))

    out.append(scenario(
        "No hours anywhere",
        "An empty availability table. Every date is empty, and it is empty "
        "before the clock is ever consulted.",
        hours=[],
        blocks=[(SUBJECT, NEXT_WED, None, None)],
        asks=[ask(NEXT_WED), ask(SUN), ask("2020-01-15")],
        durations=[0, 60],
        probes=[probe(NEXT_WED, "09:00", "10:00")]))

    out.append(scenario(
        "A booking whose time is not a time",
        "appointments.start_time is NOT NULL and is only ever written by "
        "the booking route, so an unreadable one is a corrupted row rather "
        "than somebody's mistake. calendar_logic does not catch it, and the "
        "port must not catch it either: both sides raise.",
        hours=[(SUBJECT, 3, "09:00", "12:00", 60)],
        booked=[(SUBJECT, NEXT_WED, "oops", "10:00", "confirmed")],
        asks=[ask(NEXT_WED), ask(THU)],
        durations=[0, 60],
        probes=[probe(NEXT_WED, "09:00", "10:00")]))

    return out


# ---------------------------------------------------------------------------
# The Python side
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def frozen(calendar_logic, when):
    """Pin datetime.now() inside calendar_logic to a fixed wall clock.

    Same shape as the one in tests/test_calendar_logic.py: a subclass, so
    strptime and everything else on the class still work. The comparison
    would otherwise be against whatever minute the build happened to run
    in, and a build that fails at 4pm and passes at 4am is not a check.
    """
    stamp = dt.datetime.strptime(when, "%Y-%m-%dT%H:%M")
    real = calendar_logic.dt.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return stamp

    calendar_logic.dt.datetime = Frozen
    try:
        yield
    finally:
        calendar_logic.dt.datetime = real


def called(fn):
    """Run it, and record what came back or what it refused with."""
    try:
        return {"ok": fn()}
    except Exception as bad:            # noqa: BLE001 -- comparing the type
        return {"error": type(bad).__name__, "says": str(bad)}


def python_side(all_scenarios):
    """Every scenario, through the real module, the real SQL and a real DB."""
    from core import database as db
    from domain import calendar_logic
    import app as flask_app

    app = flask_app.app
    out = []
    with app.app_context():
        db.execute("DELETE FROM users")
        for who, name in ((SUBJECT, "Subject"), (OTHER, "Other")):
            db.execute(
                "INSERT INTO users (id, name, email, password_hash, role) "
                "VALUES (?, ?, ?, ?, 'provider')",
                (who, name, "%s@build.local" % name.lower(), "x"))

        for case in all_scenarios:
            for table in ("appointments", "blocked_slots", "availability"):
                db.execute("DELETE FROM " + table)
            rows = case["data"]
            for row in rows["availability"]:
                db.execute(
                    "INSERT INTO availability (provider_id, day_of_week, "
                    "start_time, end_time, slot_minutes) VALUES (?,?,?,?,?)",
                    (row["provider_id"], row["day_of_week"],
                     row["start_time"], row["end_time"], row["slot_minutes"]))
            for row in rows["blocked_slots"]:
                db.execute(
                    "INSERT INTO blocked_slots (provider_id, date, "
                    "start_time, end_time) VALUES (?,?,?,?)",
                    (row["provider_id"], row["date"], row["start_time"],
                     row["end_time"]))
            for row in rows["appointments"]:
                db.execute(
                    "INSERT INTO appointments (provider_id, client_id, date, "
                    "start_time, end_time, status) VALUES (?,?,?,?,?,?)",
                    (row["provider_id"], OTHER, row["date"],
                     row["start_time"], row["end_time"], row["status"]))

            with frozen(calendar_logic, case["now"]):
                out.append(one_scenario_in_python(calendar_logic, case))
    return out


def one_scenario_in_python(calendar_logic, case):
    answers = {"asks": [], "probes": []}
    for question in case["asks"]:
        who, date = question["provider"], question["date"]
        row = {
            "windows": called(lambda: windows_in_python(calendar_logic, who,
                                                        date)),
            "busy": called(lambda: [list(pair) for pair in
                                    calendar_logic._busy_ranges(who, date)]),
            "free": called(lambda: calendar_logic.get_free_slots(who, date)),
            "starts": {},
        }
        for minutes in case["durations"]:
            row["starts"][str(minutes)] = called(
                lambda m=minutes: calendar_logic.slot_starts_for(who, date, m))
        answers["asks"].append(row)

    for point in case["probes"]:
        answers["probes"].append(called(
            lambda p=point: calendar_logic.is_slot_free(
                p["provider"], p["date"], p["start"], p["end"])))
    return answers


def windows_in_python(calendar_logic, who, date):
    """_windows_for, parsed the same way get_free_slots parses it.

    Projected to the three columns the SELECT actually asks for, so the two
    sides are compared on what the engine reads rather than on what the row
    happens to carry.
    """
    target = calendar_logic.dt.datetime.strptime(date, "%Y-%m-%d").date()
    return [[w["start_time"], w["end_time"], w["slot_minutes"]]
            for w in calendar_logic._windows_for(who, target)]


# ---------------------------------------------------------------------------
# The JavaScript side
# ---------------------------------------------------------------------------
SLOTS_JS = """(cases) => cases.map((sc) => {
  const call = (fn) => {
    try { return { ok: fn() }; }
    catch (e) { return { error: e.name, says: e.message }; }
  };
  const out = { asks: [], probes: [] };
  sc.asks.forEach((q) => {
    const row = {};
    row.windows = call(() =>
      AlmanacSlots.windowsFor(sc.data, q.provider,
                              AlmanacSlots.parseDate(q.date))
        .map((w) => [w.start_time, w.end_time, w.slot_minutes]));
    row.busy = call(() => AlmanacSlots.busyRanges(sc.data, q.provider, q.date));
    row.free = call(() =>
      AlmanacSlots.getFreeSlots(sc.data, q.provider, q.date, sc.now));
    row.starts = {};
    sc.durations.forEach((m) => {
      row.starts[String(m)] = call(() =>
        AlmanacSlots.slotStartsFor(sc.data, q.provider, q.date, m, sc.now));
    });
    out.asks.push(row);
  });
  sc.probes.forEach((p) => {
    out.probes.push(call(() =>
      AlmanacSlots.isSlotFree(sc.data, p.provider, p.date, p.start, p.end,
                              sc.now)));
  });
  return out;
})"""


@contextlib.contextmanager
def browser(sources):
    """A page with the bundle's JavaScript in it, and no tolerance for
    errors.

    about:blank, so there is no origin and no storage -- which is a fair
    approximation of the file:// case the published page also has to work
    in.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        stop("this build runs the JavaScript it is about to publish against "
             "the Python it was ported from, and that needs a browser.\n"
             "  pip install playwright && python -m playwright install chromium\n"
             "There is no --skip-checks flag on purpose: an unchecked port "
             "of the slot engine is the one thing this script exists to "
             "prevent.")

    page_html = ("<!doctype html><html><head><meta charset=\"utf-8\">"
                 "<title>build check</title></head><body>"
                 + "".join("<script>\n%s\n</script>" % text for text in sources)
                 + "</body></html>")

    with sync_playwright() as pw:
        options = {}
        if os.path.exists(CHROME):
            options["executable_path"] = CHROME
        instance = pw.chromium.launch(**options)
        try:
            page = instance.new_page()
            problems = []
            page.on("pageerror", lambda bad: problems.append(str(bad)))
            page.on("console", lambda msg: problems.append(msg.text)
                    if msg.type == "error" else None)
            page.set_content(page_html)
            if problems:
                stop("the bundle's JavaScript does not load:\n  "
                     + "\n  ".join(problems))
            yield page, problems
        finally:
            instance.close()


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------
def _keys_differ(want, got, path, found):
    for key in sorted(set(want) | set(got)):
        where = "%s.%s" % (path, key)
        if key not in want:
            found.append("%s: only the browser has it (%r)" % (where, got[key]))
        elif key not in got:
            found.append("%s: only python has it (%r)" % (where, want[key]))
        else:
            differences(want[key], got[key], where, found)


def _items_differ(want, got, path, found):
    if len(want) != len(got):
        found.append("%s: python has %d, browser has %d\n      python:  %r"
                     "\n      browser: %r"
                     % (path or ".", len(want), len(got), want, got))
        return
    for index, (mine, yours) in enumerate(zip(want, got)):
        differences(mine, yours, "%s[%d]" % (path, index), found)


def _same_leaf(want, got):
    """Whether two values at the bottom of a payload agree.

    Numbers compare across int and float, because JSON has one number type.
    A bool never compares equal to a number, though: True == 1 in Python,
    and is_slot_free coming back as 1 instead of true is precisely the kind
    of thing this is for.
    """
    if isinstance(want, bool) != isinstance(got, bool):
        return False
    return want == got


def differences(want, got, path="", found=None):
    """Every place two payloads disagree, with the path to each."""
    if found is None:
        found = []
    if isinstance(want, dict) and isinstance(got, dict):
        _keys_differ(want, got, path, found)
    elif isinstance(want, (list, tuple)) and isinstance(got, list):
        _items_differ(list(want), got, path, found)
    elif not _same_leaf(want, got):
        found.append("%s: python %r, browser %r" % (path or ".", want, got))
    return found


def outcome_difference(label, mine, yours):
    """Compare two results, either of which may be a refusal.

    The wording is not compared. One side is Python's own ValueError and the
    other is a throw from slots.js, and no phrasing will ever make those the
    same string -- so what is compared is that both refused, and that what
    each raised is something that side is allowed to raise. A TypeError out
    of the browser is a bug in the port, not a refusal, and is reported.
    """
    mine_refused = "error" in mine
    yours_refused = "error" in yours
    if mine_refused and mine["error"] not in PY_REFUSALS:
        return ["%s: python raised %s: %s, which is not a refusal -- it is a "
                "bug in calendar_logic" % (label, mine["error"], mine["says"])]
    if yours_refused and yours["error"] not in JS_REFUSALS:
        return ["%s: the browser raised %s: %s, which is not a refusal -- it "
                "is a bug in the port" % (label, yours["error"], yours["says"])]
    if mine_refused and not yours_refused:
        return ["%s: python refused (%s: %s), the browser returned %r"
                % (label, mine["error"], mine["says"], yours["ok"])]
    if yours_refused and not mine_refused:
        return ["%s: python returned %r, the browser refused (%s: %s)"
                % (label, mine["ok"], yours["error"], yours["says"])]
    if mine_refused and yours_refused:
        return []
    return differences(mine["ok"], yours["ok"], label)


def compare(all_scenarios, ours, theirs):
    """Every difference, over every scenario. Empty means they agree."""
    wrong = []
    refusals = 0
    compared = 0
    for case, mine, yours in zip(all_scenarios, ours, theirs):
        if yours is None:
            wrong.append("%s: the browser answered nothing" % case["name"])
            continue
        for question, a, b in zip(case["asks"], mine["asks"], yours["asks"]):
            head = "%s / %s, provider %d" % (case["name"], question["date"],
                                             question["provider"])
            for part in ("windows", "busy", "free"):
                compared += 1
                refusals += 1 if "error" in a[part] else 0
                wrong += outcome_difference("%s: %s" % (head, part),
                                            a[part], b[part])
            for minutes in sorted(a["starts"]):
                compared += 1
                got = b["starts"].get(minutes, {"error": "Missing",
                                                "says": "no answer"})
                refusals += 1 if "error" in a["starts"][minutes] else 0
                wrong += outcome_difference(
                    "%s: slot_starts_for(%s)" % (head, minutes),
                    a["starts"][minutes], got)
        for point, a, b in zip(case["probes"], mine["probes"],
                               yours["probes"]):
            compared += 1
            refusals += 1 if "error" in a else 0
            wrong += outcome_difference(
                "%s: is_slot_free(%s, %s, %s)"
                % (case["name"], point["date"], point["start"], point["end"]),
                a, b)
    return wrong, compared, refusals


def refuse_ties(all_scenarios, ours):
    """Stop if any scenario makes the comparison depend on row order.

    SQLite returns the rows of an unordered SELECT in whatever order it
    happened to produce them, and the slot list is sorted on the start
    alone, stably. So two overlapping windows that produce the same start
    with *different* ends would be ordered by SQLite on one side and by
    array order on the other, and this build would pass or fail at random.

    Overlapping windows are in the matrix on purpose, so the requirement is
    that they not tie -- and the requirement is enforced here rather than
    remembered.
    """
    tied = []
    for case, answers in zip(all_scenarios, ours):
        for question, row in zip(case["asks"], answers["asks"]):
            if "ok" not in row["free"]:
                continue
            ends = {}
            for slot in row["free"]["ok"]:
                if slot["start"] in ends and ends[slot["start"]] != slot["end"]:
                    tied.append("%s / %s: %s ends at both %s and %s"
                                % (case["name"], question["date"],
                                   slot["start"], ends[slot["start"]],
                                   slot["end"]))
                ends[slot["start"]] = slot["end"]
    if tied:
        stop("these scenarios produce two slots with the same start and "
             "different ends, so their order is SQLite's choice on one side "
             "and the array's on the other and this build would pass or fail "
             "at random. Nudge a window:\n  " + "\n  ".join(tied))


def report(wrong):
    if not wrong:
        return
    shown = wrong[:30]
    stop("the browser build disagrees with domain/calendar_logic.py in %d "
         "place%s. Nothing has been written to docs/app.\n  %s%s"
         % (len(wrong), "" if len(wrong) == 1 else "s", "\n  ".join(shown),
            "\n  ... and %d more" % (len(wrong) - len(shown))
            if len(wrong) > len(shown) else ""))


def run_checks(source, all_scenarios, ours):
    """Load one version of slots.js and compare it against the Python."""
    payload = [{"name": c["name"], "now": c["now"], "data": c["data"],
                "asks": c["asks"], "durations": c["durations"],
                "probes": c["probes"]}
               for c in all_scenarios]
    with browser([source]) as (page, problems):
        theirs = page.evaluate(SLOTS_JS, payload)
        wrong, compared, refusals = compare(all_scenarios, ours, theirs)
        if problems:
            wrong.append("the bundle's JavaScript logged errors while being "
                         "checked: " + "; ".join(problems))
    return wrong, compared, refusals


# ---------------------------------------------------------------------------
# Proving it bites
# ---------------------------------------------------------------------------
# (name, what to find in slots.js, what to put there instead, one sentence on
# what the sabotage does). Every one is a single unique string in the
# published file, so a miss is a loud failure rather than a silent pass.
SABOTAGE = [
    ("past-date",
     "if (target.iso < clock.date) {",
     "if (false) {",
     "stop treating a date before today as entirely past"),
    ("exact-now",
     "if (slotStart <= earliest) {",
     "if (slotStart < earliest) {",
     "offer the slot that starts at this very minute"),
    ("overlap",
     "return slotStart < range[1] && slotEnd > range[0];",
     "return slotStart >= range[0] && slotEnd <= range[1];",
     "require a busy range to contain a slot rather than clip it"),
    ("whole-day",
     "    if (start === null || start === undefined) {\n"
     "      return [0, MINUTES_IN_A_DAY];",
     "    if (start === null || start === undefined) {\n"
     "      return [0, 0];",
     "read a NULL/NULL block as zero length instead of the whole day"),
    ("open-end",
     "      var last = (end === null || end === undefined)\n"
     "        ? MINUTES_IN_A_DAY : toMinutes(end);",
     "      var last = (end === null || end === undefined)\n"
     "        ? first : toMinutes(end);",
     "read a block with a start and no end as zero length"),
    ("cancelled",
     "             row.status === 'confirmed';",
     "             row.status !== 'cancelled';",
     "treat completed appointments as busy as well as confirmed ones"),
    ("provider",
     "      return row.provider_id === providerId && row.date === dateStr;",
     "      return row.date === dateStr;",
     "drop the provider_id filter on blocks"),
    ("span-offgrid",
     "      if (following === undefined) {\n"
     "        return false;                   // not the start of a free slot",
     "      if (following === undefined) {\n"
     "        return true;                    // not the start of a free slot",
     "call a span bookable when it does not start on a free slot"),
    ("span-exact",
     "    return cursor === endTime;",
     "    return true;",
     "stop requiring a span to end exactly on a slot boundary"),
    ("weekday",
     "            Math.floor(year / 400) + offsets[date.month - 1] + "
     "date.day) % 7;",
     "            Math.floor(year / 400) + offsets[date.month - 1] + "
     "date.day + 1) % 7;",
     "shift every weekday by one, so Monday's hours land on Tuesday"),
    ("format",
     "    return pad2(hours) + ':' + pad2(minutes);",
     "    return hours + ':' + pad2(minutes);",
     "stop zero-padding the hour, so 09:00 becomes 9:00"),
    ("unsorted",
     "    slots.sort(function (a, b) {",
     "    [].sort(function (a, b) {",
     "hand the slots back in window order instead of sorted"),
]


def prove(source, all_scenarios, ours):
    """Break the published bundle on purpose and require every break to be
    caught. A comparison that cannot fail reads exactly like one that
    passed, so this is the only evidence that it can."""
    survived = []
    print("proving the check bites -- %d deliberate breakages of the "
          "published slots.js:" % len(SABOTAGE))
    for name, old, new, what in SABOTAGE:
        if source.count(old) != 1:
            stop("the sabotage %r has nothing to break: expected exactly one "
                 "match in the published slots.js, found %d. The port has "
                 "moved; fix the anchor in tools/build_static.py.\n"
                 "  looking for: %r" % (name, source.count(old), old[:90]))
        broken = source.replace(old, new)
        wrong, _compared, _refusals = run_checks(broken, all_scenarios, ours)
        if wrong:
            print("  caught   %-12s %s" % (name, what))
            print("             first difference: %s"
                  % wrong[0].splitlines()[0][:140])
        else:
            print("  SURVIVED %-12s %s" % (name, what))
            survived.append("%s -- %s" % (name, what))

    if survived:
        stop("%d sabotage%s survived every check, so the matrix has a hole "
             "there and a real port of the same mistake would be published "
             "without a word:\n  %s"
             % (len(survived), "" if len(survived) == 1 else "s",
                "\n  ".join(survived)))
    print("  all %d caught." % len(SABOTAGE))


# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------
def scenarios_js(all_scenarios):
    """The worked examples the page opens with, inlined as JavaScript.

    Only the scenarios marked `demo`: the matrix also holds corrupted rows
    and dates that are not dates, which belong in a comparison and not in a
    control somebody is meant to learn from.
    """
    presets = [{"name": c["name"], "note": c["note"], "now": c["now"],
                "date": c["date"], "day": c["day"], "duration": c["duration"],
                "data": c["data"]}
               for c in all_scenarios if c["demo"]]
    if not presets:
        stop("no scenario is marked demo=True, so the page would open empty")
    body = json.dumps({"providerId": SUBJECT, "presets": presets},
                      indent=2, sort_keys=True)
    return (
        "/* Generated by tools/build_static.py from the scenarios in it.\n"
        " *\n"
        " * These are not decoration: every one of them is a case the build\n"
        " * ran through both domain/calendar_logic.py and js/slots.js and\n"
        " * required to agree exactly. What the page opens on is a case that\n"
        " * was checked.\n"
        " *\n"
        " * Inlined as .js rather than fetched as .json so that opening\n"
        " * index.html straight off the disk works: a fetch() of a relative\n"
        " * URL is blocked by the file:// origin rules, and a <script src>\n"
        " * is not. */\n"
        "var AlmanacScenarios = %s;\n" % body)


def collect(all_scenarios):
    """Everything the bundle is made of, as {path in docs/app: text}."""
    written = {}
    written["js/slots.js"] = read(os.path.join(SRC, "js", "slots.js"))
    written["js/demo.js"] = read(os.path.join(SRC, "js", "demo.js"))
    written["js/scenarios.js"] = scenarios_js(all_scenarios)
    written["css/style.css"] = (
        BANNER % "static/css/style.css"
        + read(os.path.join(ROOT, "static", "css", "style.css")))
    written["css/demo.css"] = read(os.path.join(SRC, "css", "demo.css"))
    written["index.html"] = read(os.path.join(SRC, "index.html"))

    if REPO not in written["index.html"]:
        stop("the page no longer links back to the repository. The banner "
             "has to say where this came from.")
    return written


def prune(kept):
    """Delete anything left in docs/app/ from an older build.

    Without this a renamed file lives on and is still loaded, which is the
    one failure mode a generated directory has that a hand-written one does
    not.
    """
    if not os.path.isdir(OUT):
        return
    for here, _dirs, names in os.walk(OUT):
        for name in names:
            path = os.path.join(here, name)
            if os.path.relpath(path, OUT).replace("\\", "/") not in kept:
                os.remove(path)
                print("  removed stale %s" % os.path.relpath(path, OUT))


def main():
    proving = "--prove" in sys.argv[1:]

    all_scenarios = scenarios()
    written = collect(all_scenarios)

    print("running %d scenarios through domain/calendar_logic.py..."
          % len(all_scenarios))
    ours = python_side(all_scenarios)
    refuse_ties(all_scenarios, ours)

    if proving:
        prove(written["js/slots.js"], all_scenarios, ours)
        return

    print("checking the port against the Python it came from...")
    wrong, compared, refusals = run_checks(written["js/slots.js"],
                                           all_scenarios, ours)
    report(wrong)
    print("  calendar_logic.py == slots.js   %d answers over %d scenarios, "
          "%d of them refusals" % (compared, len(all_scenarios), refusals))

    for name, body in sorted(written.items()):
        write(os.path.join(OUT, name.replace("/", os.sep)), body)
    prune(set(written))

    total = sum(len(body.encode("utf-8")) for body in written.values())
    print("wrote %d files to docs/app (%.0f KB)"
          % (len(written), total / 1024.0))
    print("  serve it:  python -m http.server -d docs 8000  ->  "
          "http://127.0.0.1:8000/app/")
    print("  prove the check bites:  python tools/build_static.py --prove")


if __name__ == "__main__":
    # A database of this build's own, and no mail or timer, before anything
    # from the app is imported: core.config reads DATABASE_URL at import
    # time and core.database caches what it found.
    _TMP = tempfile.mkdtemp(prefix="almanac-build-")
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "build.db")
    os.environ.setdefault("SECRET_KEY",
                          "build-secret-long-enough-for-hs256-and-then-some")
    os.environ.setdefault("SMTP_HOST", "")
    os.environ.setdefault("MAIL_ENABLED", "0")
    os.environ.setdefault("REMINDERS_ENABLED", "0")
    try:
        main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

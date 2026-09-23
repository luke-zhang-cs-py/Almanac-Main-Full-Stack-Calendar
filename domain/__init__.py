"""
domain/
--------
What Almanac is actually about, with no HTTP and no email in it.

Every module here talks to `core.database` and to the others in this
package, and none of them imports `routes` or `notify`. That is the point of
the boundary: the rules about when a slot is free, what an invite costs and
whether a conversion fits under the ceiling are the part worth testing
directly, and they are testable directly precisely because nothing in here
needs a request or a mail server to run.

  calendar_logic.py  the free-slot engine: recurring weekly hours, minus
                     one-off blocks, minus confirmed bookings, tiled into
                     bookable slots. Pure computation over rows -- which is
                     why docs/app/ can run a port of it in a browser.
  coffee_chats.py    the invite lifecycle: tokens, expiry, and a guest
                     booking without an account
  offerings.py       the priced catalogue per provider; money as integer
                     minor units
  pounds.py          Canadian dollars into pounds, crossed through the euro,
                     against a per-user ceiling
  schedule.py        a personal timetable imported from the standalone
                     planner, and what may be reminded about
"""

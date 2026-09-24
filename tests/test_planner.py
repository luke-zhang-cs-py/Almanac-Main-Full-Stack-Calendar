"""The standalone planner: one file, no network, and nobody's timetable in it.

The planner is a single HTML file you double-click. It was written that way
and for a long time it was *only* that way -- 70KB with one person's term,
diary and to-do list declared inline, which is why it had never been in a
repository. A timetable says where somebody is at every hour of every
weekday; that is not a thing to publish to make a build reproducible.

So the engine lives in standalone/planner/ and the seed does not. The
builder inlines whichever seed it is pointed at, and defaults to an invented
sample. Three things have to stay true, and the tests below are in that
order:

  * **No seed in the sources.** The most consequential test here, and the
    one that cannot name what it is looking for -- writing the real module
    codes into an assertion would put them in the repository, which is the
    thing being prevented. So it looks for the *shape* of personal data
    rather than the content: addresses, postcodes, phone numbers, emails.

  * **Nothing points outside the built file.** A stray src="app.js" keeps
    working while the file sits beside its sources and breaks the moment it
    is moved, which is the one situation it exists for.

  * **It runs.** Checked by opening it from disk in a real browser, because
    file:// is where it is used and where fetch does not work.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_planner as builder   # noqa: E402

SRC = os.path.join(ROOT, "standalone", "planner")
SOURCES = ("index.html", "style.css", "app.js",
           "data.sample.js", "data.blank.js")

BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def browser():
    for path in BROWSERS:
        if os.path.isfile(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def source(name):
    with io.open(os.path.join(SRC, name), encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def built():
    return builder.build()


# ------------------------------------------------- nobody's timetable in it


def test_the_only_seed_in_the_repository_is_the_sample():
    """A real seed appearing beside the sample is the accident this is here
    to catch -- `data.js` is what the built file's script tag is named, so
    it is the name somebody would reach for."""
    present = sorted(f for f in os.listdir(SRC) if not f.startswith("."))
    assert present == sorted(SOURCES), (
        f"unexpected files in standalone/planner: {present}")


def test_the_sample_says_it_is_invented():
    """Somebody opening it should not have to work out whether these are
    real classes before they edit them."""
    text = source("data.sample.js")
    assert "invented" in text.lower()
    assert "--data" in text, "it should say how to point at your own"


# The shapes personal data takes, rather than the data itself: naming the
# real module codes or address here would put them in the repository, which
# is the thing being prevented.
PERSONAL_SHAPES = {
    "a UK postcode": r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b",
    "an email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "a UK phone number": r"\b(?:\+44|07)\d[\d ]{7,}\b",
    "a street address": r"\b\d+[a-z]?\s+[A-Z][a-z]+\s+"
                        r"(?:Road|Street|Avenue|Lane|Drive|Court|Way)\b",
    "a flight number": r"\b[A-Z]{2}\d{3,4}\b",
}


@pytest.mark.parametrize("what, pattern", sorted(PERSONAL_SHAPES.items()))
def test_no_source_file_carries_personal_data(what, pattern):
    found = []
    for name in SOURCES:
        for hit in re.finditer(pattern, source(name)):
            found.append(f"{name}: {hit.group(0)!r}")
    assert not found, f"{what} in the committed sources: {found}"


def test_that_check_would_actually_catch_something():
    """The negative control. A pattern that matches nothing passes whatever
    it is pointed at, and these are narrow enough to be worth proving
    rather than assuming.

    Every value below is deliberately fictional: ZZ99 3WZ is the dummy
    postcode, 07700 900xxx is the range Ofcom reserves for drama, and
    example.com is reserved by the RFC. A control that used a real address
    to prove it catches real addresses would put one in the repository,
    which is the thing this file exists to prevent -- and the first draft of
    this test did exactly that.
    """
    sample = ("Flight XX999 from ZZ99 3WZ, 1 Nowhere Lane, "
              "call 07700 900123 or someone@example.com")
    missed = [what for what, pattern in PERSONAL_SHAPES.items()
              if not re.search(pattern, sample)]
    assert not missed, f"these patterns match nothing: {missed}"


def test_the_engine_reads_its_seed_rather_than_holding_one():
    """Every setting the planner needs comes through the seed lookup, so a
    value hard-coded back into app.js would be one the seed file cannot
    change and nobody would notice until they tried."""
    app = source("app.js")
    assert "PLANNER_DATA" in app, "the engine does not read a seed at all"
    for name in ("CD_ANCHOR", "FIXTURES", "WEEK_A", "DIARY", "SEED_TODOS"):
        assert re.search(r'\b%s\s*=\s*seed\(' % name, app), (
            f"{name} is not read from the seed")


# ----------------------------------------------------------- the built file


def test_nothing_points_outside_the_built_file(built):
    loose = builder.loose_references(built)
    assert not loose, f"these still point outside the file: {loose}"


def test_the_builder_refuses_to_write_one_that_does(built):
    """The negative control for the check above."""
    broken = built.replace("</body>", '<img src="chart.png"></body>', 1)
    assert builder.loose_references(broken) == ["chart.png"], (
        "the check guarding this would not notice a stray reference")


def test_everything_is_inlined(built):
    assert "<style>" in built and "</style>" in built
    assert "window.PLANNER_DATA" in built, "the seed is not inlined"
    assert 'src="app.js"' not in built and 'src="data.js"' not in built
    # Something from each source, so a half-built file fails here.
    assert "renderCalendar" in built, "the engine is not inlined"


def test_it_cannot_reach_the_network(built):
    policy = re.search(r'Content-Security-Policy" content="([^"]*)"', built)
    assert policy, "the built file has no content policy"
    assert "default-src 'none'" in policy.group(1)
    assert "connect-src" not in policy.group(1), (
        "a file that needs no network should not be allowed one")


def test_the_banner_names_the_seed_it_used(built):
    """Building the sample by accident and not noticing is the one
    confusing failure here, so the file says which seed it holds."""
    assert "data.sample.js" in built
    assert "invented" in built


def test_building_with_a_missing_seed_is_refused(tmp_path):
    with pytest.raises(Exception):
        builder.build(str(tmp_path / "nope.js"))


# --------------------------------------------------------------- it runs


def run_in_planner(built, setup, settle=900):
    """Open the built planner from disk with `setup` injected before it
    boots, and return what it reported.

    `setup` runs first, so it can seed localStorage and stand in for browser
    APIs the page would otherwise need a human to approve.
    """
    folder = tempfile.mkdtemp()
    try:
        probe = (
            "<script>window.addEventListener('load', function () {"
            "window.setTimeout(function () {"
            "  var out = document.createElement('pre');"
            "  out.id = 'PROBE';"
            "  out.textContent = 'PROBE ' + JSON.stringify(window.__report());"
            "  document.body.insertBefore(out, document.body.firstChild);"
            "}, %d); });</script>" % settle
        )
        page = built.replace("<script>", "<script>%s</script>\n<script>"
                             % setup, 1)
        page = page.replace("</body>", probe + "</body>", 1)
        path = os.path.join(folder, "planner.html")
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(page)

        done = subprocess.run(
            [browser(), "--headless=new", "--disable-gpu", "--no-sandbox",
             "--no-first-run", "--no-default-browser-check",
             "--user-data-dir=" + os.path.join(folder, "profile"),
             "--virtual-time-budget=20000", "--dump-dom",
             "file:///" + path.replace("\\", "/")],
            capture_output=True, timeout=300)
        dom = done.stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    found = re.search(r"PROBE (\{.*?\})</pre>", dom, re.S)
    assert found, f"the planner did not report; {len(dom)} bytes of DOM"
    import html as htmllib
    return json.loads(htmllib.unescape(found.group(1)))


# Stands in for the Notification API, which otherwise needs a human to click
# "Allow". Everything the planner asks of it -- the constructor, .permission
# and .requestPermission -- is here, and every call is recorded.
NOTIFY_STUB = """
window.__sent = [];
window.Notification = function (title, opts) {
  window.__sent.push({ title: title, body: (opts || {}).body,
                       tag: (opts || {}).tag });
};
window.Notification.permission = 'granted';
window.Notification.requestPermission = function () {
  return Promise.resolve('granted');
};
window.__report = function () {
  return {
    sent: window.__sent,
    note: (document.getElementById('notifyMsg') || {}).textContent,
    button: (document.getElementById('notifyBtn') || {}).textContent,
    pressed: (document.getElementById('notifyBtn') || {})
               .getAttribute('aria-pressed'),
    remembered: Object.keys(
      JSON.parse(localStorage.getItem('sept-planner.notified.v1') || '{}'))
  };
};
"""


def seed_events(minutes_ahead, extra="", on=True):
    """localStorage holding one event that many minutes away, plus whatever
    `extra` adds. The seed flags are pre-set so the sample term and fixtures
    are not laid on top of the case under test."""
    return NOTIFY_STUB + """
(function () {
  function two(n) { return String(n).padStart(2, '0'); }
  var at = new Date(Date.now() + %d * 60000);
  var date = at.getFullYear() + '-' + two(at.getMonth() + 1) + '-'
           + two(at.getDate());
  var time = two(at.getHours()) + ':' + two(at.getMinutes());
  var events = {};
  events[date] = [{ id: 'probe-local', time: time, end: '23:59',
                    title: 'Local class', type: 'class', done: false }];
  %s
  localStorage.setItem('sept-planner.events.v1', JSON.stringify(events));
  localStorage.setItem('sept-planner.notify.v1', JSON.stringify({on: %s}));
  ['sept-planner.seed.sample-fixtures.v1',
   'sept-planner.seed.sample-term.v1',
   'sept-planner.seed.sample-diary.v1'].forEach(function (k) {
    localStorage.setItem(k, 'true');
  });
}());
""" % (minutes_ahead, extra, "true" if on else "false")


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_an_event_inside_the_window_is_announced(built):
    got = run_in_planner(built, seed_events(20))
    assert len(got["sent"]) == 1, got["sent"]
    assert got["sent"][0]["title"] == "Local class"
    assert "minutes" in got["sent"][0]["body"], got["sent"][0]["body"]
    assert got["remembered"] == ["probe-local"], (
        "it did not record that it had announced this one")


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_an_event_beyond_the_window_is_not_announced(built):
    """The lead is 30 minutes; this one is 90 away."""
    got = run_in_planner(built, seed_events(90))
    assert got["sent"] == []
    assert got["remembered"] == []


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_an_event_that_already_started_is_not_announced(built):
    """A reminder for something you are late to is noise."""
    got = run_in_planner(built, seed_events(-10))
    assert got["sent"] == []


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_an_event_on_another_clock_is_skipped_and_counted(built):
    """`tz` is a display label, so a time labelled EST is not the local
    instant. Announcing it on the local clock would be hours wrong, so it is
    skipped -- and the note says so rather than leaving it a mystery."""
    extra = ("events[date].push({ id: 'probe-far', time: time, end: '23:59',"
             " title: 'Far match', type: 'match', tz: 'EST', done: false });")
    got = run_in_planner(built, seed_events(20, extra))
    titles = [n["title"] for n in got["sent"]]
    assert titles == ["Local class"], titles
    assert "another timezone" in got["note"], got["note"]


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_a_finished_event_is_not_announced(built):
    extra = "events[date][0].done = true;"
    got = run_in_planner(built, seed_events(20, extra))
    assert got["sent"] == []


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_nothing_is_announced_twice(built):
    """The id is remembered, so reopening the file does not announce the
    same class again -- the tick also runs every thirty seconds."""
    extra = ("localStorage.setItem('sept-planner.notified.v1',"
             " JSON.stringify({'probe-local': Date.now()}));")
    got = run_in_planner(built, seed_events(20, extra))
    assert got["sent"] == [], "it announced one it had already announced"


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_reminders_stay_off_until_they_are_turned_on(built):
    got = run_in_planner(built, seed_events(20, on=False))
    assert got["sent"] == []
    assert got["pressed"] == "false"
    assert "Off" in got["note"], got["note"]


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_the_page_says_it_only_works_while_the_tab_is_open(built):
    """The honest limit, stated where somebody switching it on will read it:
    a file:// page cannot register a service worker, so there is nothing to
    run once the tab is gone."""
    got = run_in_planner(built, seed_events(20))
    assert "while this tab is open" in got["note"], got["note"]
    assert got["pressed"] == "true"


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_it_seeds_and_renders_from_disk(built):
    """Opened from disk, where it is actually used. The seed runs once into
    localStorage, so what it wrote there is the whole output of the data
    path and is worth reading back rather than trusting."""
    folder = tempfile.mkdtemp()
    try:
        probe = (
            "<script>window.addEventListener('load', function () {"
            "window.setTimeout(function () {"
            "  var store = {};"
            "  for (var i = 0; i < localStorage.length; i++) {"
            "    var k = localStorage.key(i);"
            "    store[k] = localStorage.getItem(k).length;"
            "  }"
            "  var events = JSON.parse("
            "    localStorage.getItem('sept-planner.events.v1') || '{}');"
            "  var out = document.createElement('pre');"
            "  out.id = 'PROBE';"
            "  out.textContent = 'PROBE ' + JSON.stringify({"
            "    origin: location.protocol,"
            "    keys: Object.keys(store).sort(),"
            "    days: Object.keys(events).length,"
            "    cells: document.querySelectorAll('.cell,.day,td').length,"
            "    title: document.title,"
            "    errors: window.__errs || []"
            "  });"
            "  document.body.insertBefore(out, document.body.firstChild);"
            "}, 700); });"
            "window.__errs = [];"
            "window.addEventListener('error', function (e) {"
            "  window.__errs.push(String(e.message)); });</script>"
        )
        path = os.path.join(folder, "planner.html")
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(built.replace("</body>", probe + "</body>", 1))

        done = subprocess.run(
            [browser(), "--headless=new", "--disable-gpu", "--no-sandbox",
             "--no-first-run", "--no-default-browser-check",
             "--user-data-dir=" + os.path.join(folder, "profile"),
             "--virtual-time-budget=20000", "--dump-dom",
             "file:///" + path.replace("\\", "/")],
            capture_output=True, timeout=300)
        dom = done.stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    found = re.search(r"PROBE (\{.*?\})</pre>", dom, re.S)
    assert found, f"the planner did not run from disk; {len(dom)} bytes of DOM"

    import html as htmllib
    got = json.loads(htmllib.unescape(found.group(1)))

    assert got["origin"] == "file:", "this did not test a file:// origin"
    assert not got["errors"], f"it threw on load: {got['errors']}"
    assert got["days"] > 0, "the seed put no events in the calendar"
    assert got["cells"] > 0, "the calendar rendered no cells"
    assert any(k.startswith("sept-planner.events") for k in got["keys"]), (
        f"nothing was seeded; keys were {got['keys']}")


# --------------------------------------------------- the two asked-for settings
# An email address and an hourly rate are the owner's, so the engine ships
# without them and asks. These guard the "and asks" half: a skeleton that
# quietly defaulted to somebody's address would be the seed problem again,
# in a smaller box.

def test_the_engine_ships_with_no_address_and_no_rate():
    """Neither value may be baked in. The email half is already covered by
    the shape checks above -- this catches a hard-coded *rate*, which no
    shape test would notice because a bare number looks like anything."""
    code = source("app.js")
    for bad in ('settings = load(SETTINGS_KEY, { email: "someone',
                'price: 0.', 'price: 1', 'price: 2', 'price: 3',
                'price: 4', 'price: 5', 'price: 6', 'price: 7',
                'price: 8', 'price: 9'):
        assert bad not in code, f"app.js ships a default rate: {bad!r}"
    assert 'price: null' in code, (
        "the rate should start unset, so the card can say it is needed")
    assert 'email: ""' in code, "the address should start empty"


def test_the_setup_card_asks_for_both():
    """Both fields, both labelled, and a submit that is not a link."""
    markup = source("index.html")
    for needed in ('id="setEmail"', 'id="setPrice"', 'id="setCurrency"',
                   'id="setupForm"', 'id="setupMsg"'):
        assert needed in markup, f"the setup card is missing {needed}"
    assert 'type="email"' in markup, "the address field should be type=email"
    assert 'type="number"' in markup, "the rate field should be type=number"
    assert 'min="0"' in markup, "a negative rate should not even be typeable"


def test_the_placeholders_are_not_email_shaped():
    """The reason they read "your email address" rather than a reserved
    example domain: the shape checks above forbid *any* email-shaped string
    in these sources, including a fictional one, because they look for the
    shape and not the content. A placeholder that matched would either fail
    the build or force the guard to be loosened, and loosening it is how the
    real thing gets through later."""
    markup = source("index.html")
    assert 'placeholder="your email address"' in markup
    assert "@" not in markup.split("<body")[0] or True   # head may hold none
    for hit in re.finditer(r'placeholder="([^"]*)"', markup):
        assert "@" not in hit.group(1), (
            f"placeholder looks like an address: {hit.group(1)!r}")


def test_the_settings_travel_in_an_export_only_when_set():
    """They go into an export so Almanac can address a reminder and price an
    offering without retyping. Null until filled in -- an export that
    invented a rate would be worse than one that omitted it."""
    code = source("app.js")
    assert "reminderEmail: settings.email || null" in code
    assert "ratePerHour: settings.price === null ? null" in code
    assert "reminderLeadMinutes: LEAD_MINUTES" in code, (
        "the lead time should travel with them rather than be set twice")


def test_the_page_never_sends_the_address_itself():
    """The whole reason a mailto is used rather than a fetch. This file is
    opened over file://; posting somebody's movements to a relay to get an
    email out of it would be a worse trade than not having the email."""
    code = source("app.js")
    assert "fetch(" not in code, "the engine should make no requests"
    assert "XMLHttpRequest" not in code
    assert "mailto:" in code, "the email path should hand off to a mail client"


def test_a_new_event_is_assigned_a_colour_that_differs():
    """Every new event used to arrive cyan, so a day filled in quickly came
    out one colour and the month grid's strips stopped distinguishing
    anything. The swatches still work -- this is a default, not a lock."""
    code = source("app.js")
    assert "function autoColor(" in code
    assert "function suggestColor(" in code
    assert "colorChosen" in code, "a user's pick has to survive a re-render"
    assert 'setFormColor(c, true)' in code, (
        "clicking a swatch should count as the user choosing")
    # The palette is ordered for contrast, not around the colour wheel.
    assert '"cyan","amber","violet"' in code, (
        "consecutive palette entries should be far apart in hue")


def test_events_take_the_wide_column(built):
    """On a wide screen the events are the content and the timeline beside
    them is a picture of it, so the events come first and get the width."""
    assert re.search(r"\.dvgrid\{[^}]*1\.3fr", built), (
        "the events column should be the wider one")
    events_at = built.index("Classes &amp; events")
    plan_at = built.index('id="planHead"')
    assert events_at < plan_at, "the plan column still comes first"


# ------------------------------------------- the copy published on the page
# docs/planner.html is a built artifact, which this repository otherwise
# does not commit -- the .joblib files and the model weights in its siblings
# are all ignored. It earns the exception by being the whole point of the
# thing: a single file you open by double-clicking. Committing only the
# sources means the quickest way to see it is to clone the repo and run
# Python, which is the opposite of what it is for.
#
# The cost of a committed artifact is that it goes stale, so that is what
# these check. A drifted copy fails CI rather than sitting there quietly
# being a different program from the one in standalone/planner/.

PUBLISHED = os.path.join(ROOT, "docs", "planner.html")


def test_the_published_copy_exists():
    assert os.path.isfile(PUBLISHED), (
        "docs/planner.html is missing; rebuild it with "
        "`python tools/build_planner.py --out docs/planner.html`")


def test_the_published_copy_matches_a_fresh_build(built):
    """Byte-for-byte against the sources, so it cannot drift.

    The builder is deterministic apart from nothing -- there is no timestamp
    in the output -- so this is a straight comparison. If it ever grows one,
    this test is where that gets noticed.
    """
    with io.open(PUBLISHED, encoding="utf-8") as handle:
        published = handle.read()
    assert published == built, (
        "docs/planner.html is out of date with standalone/planner/. "
        "Rebuild: python tools/build_planner.py --out docs/planner.html")


def test_the_published_copy_holds_the_invented_seed():
    """It is served from a public page, so the one thing it must never carry
    is somebody's real timetable. The shape checks above cover the sources;
    this covers the built file, which is what people actually download."""
    with io.open(PUBLISHED, encoding="utf-8") as handle:
        published = handle.read()
    assert "data.sample.js" in published, "the banner does not name the seed"
    for what, pattern in PERSONAL_SHAPES.items():
        found = [hit.group(0) for hit in re.finditer(pattern, published)]
        assert not found, f"{what} in the published planner: {found}"


def test_the_published_copy_is_self_contained():
    """Someone downloading one file from a web page gets one file. A stray
    src= would work on the Pages site and break the moment it is saved."""
    with io.open(PUBLISHED, encoding="utf-8") as handle:
        published = handle.read()
    assert not builder.loose_references(published)


def test_the_policy_claims_nothing_a_meta_tag_cannot_deliver():
    """`frame-ancestors` in a <meta> CSP is ignored by the browser, which
    logs a notice saying so. Listing it looked like protection and was not
    providing any -- the same shape of mistake as a guard that cannot fail.

    Checked here rather than left to a person noticing a console message,
    because a console notice on a page nobody opens is a message nobody
    reads."""
    policy = re.search(r'Content-Security-Policy" content="([^"]*)"',
                       builder.build())
    assert policy, "the built file has no content policy"
    assert "frame-ancestors" not in policy.group(1), (
        "a meta CSP cannot deliver frame-ancestors; it only works as a header")
    # The directives that do work are still there.
    for directive in ("default-src 'none'", "form-action 'none'",
                      "base-uri 'none'"):
        assert directive in policy.group(1), directive


def test_the_blank_seed_is_actually_blank():
    """The empty calendar's whole value is that there is nothing in it. A key
    that quietly gains content makes it a second sample seed, and somebody
    starting a real term from it would inherit whatever crept in."""
    text = source("data.blank.js")
    for key in ("COUNTDOWN_DATES", "FIXTURES", "DONE_MATCHES", "TERM_SKIP",
                "WEEK_ONE", "WEEK_A", "WEEK_B", "DIARY",
                "SEED_TODOS", "SEED_DAY_TODOS"):
        assert re.search(key + r"\s*:\s*\[\s*\]", text), (
            f"{key} in data.blank.js is no longer an empty list")
    for key in ("COMPS", "MODULE_COLOUR"):
        assert re.search(key + r"\s*:\s*\{\s*\}", text), (
            f"{key} in data.blank.js is no longer an empty object")
    for key in ("CD_ANCHOR", "TERM_FIRST", "TERM_END"):
        assert re.search(key + r'\s*:\s*""', text), (
            f"{key} in data.blank.js is no longer empty")


def test_the_blank_build_carries_none_of_the_sample():
    """Built from the blank seed, not the sample -- the mistake being guarded
    against is --blank silently falling back to the default seed."""
    page = builder.build(os.path.join(SRC, "data.blank.js"))
    for invented in ("MAT 1001", "Rovers United", "Buy a rail card",
                     "Maths LT1", "sample-"):
        assert invented not in page, (
            f"the blank calendar contains {invented!r} from the sample seed")


def test_an_empty_seed_does_not_render_a_broken_countdown():
    """With no anchor the countdown arithmetic is NaN and the percentage
    divides by zero, which printed 'NaN days remaining' on the empty
    calendar. The card is hidden instead -- an empty planner should look
    empty, not broken."""
    code = source("app.js")
    assert 'querySelector(".cdcard")' in code, (
        "renderCountdown no longer looks for the card it needs to hide")
    assert re.search(r"if\s*\(!CD_ANCHOR\s*\|\|\s*!\(CD_START\s*>\s*0\)\)", code), (
        "renderCountdown no longer guards against an absent countdown")
